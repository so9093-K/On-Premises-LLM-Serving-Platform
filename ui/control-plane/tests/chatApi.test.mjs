import assert from 'node:assert/strict';
import test from 'node:test';

import { ApiError, fetchPublicModels, postChatCompletion, postPublicJson } from '../src/api.ts';
import { prepareChatRequest } from '../src/publicChatRequest.ts';

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

  const { requestId } = await postChatCompletion(null, prepareChatRequest({ model: 'local-main', stream: true, messages: [] }), controller.signal);

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
    postChatCompletion('k', prepareChatRequest({ model: 'local-main', stream: true, messages: [] }), new AbortController().signal),
    (error) => error instanceof ApiError
      && error.status === 503
      && error.code === 'MAIN_MODEL_SWITCH_IN_PROGRESS'
      && error.requestId === 'req_503',
  );
});

test('a recorded serialized body is sent without generating a second version', async (t) => {
  const calls = withFetch(t, () => new Response('{"choices":[]}', {
    status: 200,
    headers: { 'X-Request-Id': 'req_snapshot' },
  }));
  const body = { model: 'local-main', messages: [{ role: 'user', content: 'test' }] };
   const request = prepareChatRequest(body);
  const originalWireJson = request.json;
  body.messages = [{ role: 'user', content: 'changed after prepare' }];
  await postChatCompletion(null, request, new AbortController().signal);
  assert.equal(calls[0].init.body, originalWireJson);
  assert.equal(calls[0].init.headers.Accept, 'application/json');
});

test('Embedding and Risk workspaces call the public API with the user key and keep the request id', async (t) => {
  const calls = withFetch(t, (url) => (url === '/v1/risk/assessments'
    ? new Response(JSON.stringify({ error: { code: 'MODEL_UNAVAILABLE', message: 'not ready' } }), {
      status: 503,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req_risk' },
    })
    : new Response(JSON.stringify({ object: 'list', data: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req_embed' },
    })));

  const { requestId } = await postPublicJson('api-key-1', '/v1/embeddings', JSON.stringify({ model: 'local-embed', input: 'x' }));

  assert.equal(requestId, 'req_embed');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer api-key-1');
  assert.equal(calls[0].init.body, JSON.stringify({ model: 'local-embed', input: 'x' }));
  await assert.rejects(
    postPublicJson(null, '/v1/risk/assessments', JSON.stringify({ prompt: 'x' })),
    (error) => error instanceof ApiError && error.code === 'MODEL_UNAVAILABLE' && error.requestId === 'req_risk',
  );
  assert.equal(calls[1].init.headers.Authorization, undefined);
});
