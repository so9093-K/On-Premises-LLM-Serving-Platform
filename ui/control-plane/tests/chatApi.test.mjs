import assert from 'node:assert/strict';
import test from 'node:test';

import { ApiError, fetchPublicModels, postChatCompletion } from '../src/api.ts';

function withFetch(t, handler) {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ url: String(input), init });
    return handler(String(input), init);
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  return calls;
}

test('public API calls send the API key only when one was entered', async (t) => {
  const calls = withFetch(t, () => new Response(JSON.stringify({ object: 'list', data: [] }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }));

  await fetchPublicModels(null);
  await fetchPublicModels('api-key-1');

  assert.equal(calls[0].url, '/v1/models');
  assert.equal(calls[0].init.headers.Authorization, undefined);
  assert.equal(calls[1].init.headers.Authorization, 'Bearer api-key-1');
});

test('streaming chat requests ask for SSE and expose the gateway request id', async (t) => {
  const calls = withFetch(t, () => new Response('data: [DONE]\n\n', {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'X-Request-Id': 'req_stream' },
  }));
  const controller = new AbortController();

  const { requestId } = await postChatCompletion(null, { model: 'local-main', stream: true, messages: [] }, controller.signal);

  assert.equal(requestId, 'req_stream');
  assert.equal(calls[0].url, '/v1/chat/completions');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.signal, controller.signal);
  assert.equal(calls[0].init.headers.Accept, 'text/event-stream');
  assert.equal(calls[0].init.headers['Content-Type'], 'application/json');
});

test('a rejected chat request keeps the error code and falls back to the header request id', async (t) => {
  withFetch(t, () => new Response(JSON.stringify({ error: { code: 'MAIN_MODEL_SWITCH_IN_PROGRESS', message: '전환 중' } }), {
    status: 503,
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req_503' },
  }));

  await assert.rejects(
    postChatCompletion('k', { model: 'local-main', stream: true, messages: [] }, new AbortController().signal),
    (error) => error instanceof ApiError
      && error.status === 503
      && error.code === 'MAIN_MODEL_SWITCH_IN_PROGRESS'
      && error.requestId === 'req_503',
  );
});
