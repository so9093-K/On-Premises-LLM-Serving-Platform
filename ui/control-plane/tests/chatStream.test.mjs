import assert from 'node:assert/strict';
import test from 'node:test';

import { createSseParser, interpretChatEvent, readChatStream } from '../src/chatStream.ts';
import { applyChatUpdate, buildChatRequest, DEFAULT_CHAT_SETTINGS, finishTurn, startTurn } from '../src/chatSession.ts';

function chunk(delta, extra = {}) {
  return `data: ${JSON.stringify({ id: 'chatcmpl_1', object: 'chat.completion.chunk', choices: [{ index: 0, delta, ...extra }] })}\n\n`;
}

function streamOf(parts) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(typeof part === 'string' ? encoder.encode(part) : part);
      controller.close();
    },
  });
}

async function collect(parts) {
  const updates = [];
  await readChatStream(streamOf(parts), (update) => updates.push(update));
  return updates;
}

test('events are identical regardless of where the network splits lines', () => {
  const wire = `${chunk({ content: '안녕' })}: keep-alive\n\n${chunk({ content: '하세요' })}data: [DONE]\n\n`;
  const whole = createSseParser();
  const expected = [...whole.push(wire), ...whole.finish()];
  assert.equal(expected.length, 3);

  for (let size = 1; size <= 7; size += 1) {
    const parser = createSseParser();
    const events = [];
    for (let index = 0; index < wire.length; index += size) {
      events.push(...parser.push(wire.slice(index, index + size)));
    }
    events.push(...parser.finish());
    assert.deepEqual(events, expected, `split size ${size}`);
  }
});

test('CRLF framing split between the CR and LF does not create an extra event boundary', () => {
  const parser = createSseParser();
  const events = [
    ...parser.push('data: a\r'),
    ...parser.push('\ndata: b\r\n\r\n'),
    ...parser.finish(),
  ];
  assert.deepEqual(events, [{ event: 'message', data: 'a\nb' }]);
});

test('Korean text split inside a UTF-8 code point is reassembled', async () => {
  const bytes = new TextEncoder().encode(chunk({ content: '한글' }) + 'data: [DONE]\n\n');
  const cut = bytes.indexOf(0xed) + 1; // '한'의 첫 byte 뒤에서 자른다
  const updates = await collect([bytes.slice(0, cut), bytes.slice(cut)]);
  assert.equal(updates[0].content, '한글');
  assert.equal(updates.at(-1).kind, 'done');
});

test('reasoning, finish reason and usage are read from the gateway contract fields', async () => {
  const updates = await collect([
    chunk({ reasoning: '생각' }),
    chunk({ reasoning_content: ' 계속' }),
    chunk({ content: '답' }, { finish_reason: 'stop' }),
    `data: ${JSON.stringify({ id: 'chatcmpl_1', choices: [], usage: { prompt_tokens: 12, completion_tokens: 5, total_tokens: 17 } })}\n\n`,
    'data: [DONE]\n\n',
  ]);
  assert.deepEqual(updates.map((update) => update.kind), ['chunk', 'chunk', 'chunk', 'chunk', 'done']);
  assert.equal(updates[0].reasoning, '생각');
  assert.equal(updates[1].reasoning, ' 계속');
  assert.equal(updates[2].finishReason, 'stop');
  assert.deepEqual(updates[3].usage, { prompt_tokens: 12, completion_tokens: 5, total_tokens: 17 });
});

test('streaming tool calls preserve index and argument fragments', async () => {
  const updates = await collect([
    chunk({ tool_calls: [{
      index: 0,
      id: 'call_weather',
      type: 'function',
      function: { name: 'get_weather', arguments: '{"city"' },
    }] }),
    chunk({ tool_calls: [{
      index: 0,
      function: { arguments: ':"Seoul"}' },
    }] }, { finish_reason: 'tool_calls' }),
    'data: [DONE]\n\n',
  ]);
  assert.deepEqual(updates[0].toolCallDeltas, [{
    index: 0,
    id: 'call_weather',
    type: 'function',
    name: 'get_weather',
    arguments: '{"city"',
  }]);
  assert.deepEqual(updates[1].toolCallDeltas, [{
    index: 0,
    id: '',
    type: '',
    name: '',
    arguments: ':"Seoul"}',
  }]);
  assert.equal(updates[1].finishReason, 'tool_calls');
});

test('a gateway SSE error event surfaces code, message and request id', () => {
  const update = interpretChatEvent({
    event: 'error',
    data: JSON.stringify({ error: { code: 'UPSTREAM_TIMEOUT', message: '런타임 응답 시간 초과', request_id: 'req_abc' } }),
  });
  assert.deepEqual(update, {
    kind: 'error',
    code: 'UPSTREAM_TIMEOUT',
    message: '런타임 응답 시간 초과',
    requestId: 'req_abc',
  });
});

test('a final event without the trailing blank line is still delivered', async () => {
  const updates = await collect([chunk({ content: '앞' }), `data: ${JSON.stringify({ choices: [{ delta: { content: '끝' } }] })}`]);
  assert.deepEqual(updates.filter((update) => update.kind === 'chunk').map((update) => update.content), ['앞', '끝']);
  assert.equal(updates.at(-1).code, 'STREAM_INCOMPLETE');
});

test('truncated text remains visible but cannot enter successful conversation history', async () => {
  let turn = startTurn(0);
  await readChatStream(streamOf([chunk({ content: '부분 응답' })]), (update) => {
    turn = applyChatUpdate(turn, update, 10);
  });
  turn = finishTurn(turn, 20);
  assert.equal(turn.content, '부분 응답');
  assert.equal(turn.status, 'failed');
  assert.equal(turn.error.code, 'STREAM_INCOMPLETE');
  const model = { id: 'local-main', backend: 'vllm', capabilities: ['chat.completions'], request_parameters: {} };
  const history = [{ id: 1, user: '이전 질문', attachments: [], assistant: turn }];
  const request = buildChatRequest(model, DEFAULT_CHAT_SETTINGS, history, '다시 질문');
  assert.equal(request.error, null);
  assert.deepEqual(request.body.messages, [{ role: 'user', content: '다시 질문' }]);
});

test('empty and comment-only streams fail without a completion signal', async () => {
  for (const parts of [[], [': keep-alive\n\n']]) {
    const updates = await collect(parts);
    assert.equal(updates.at(-1).code, 'STREAM_INCOMPLETE');
  }
});

test('a final DONE without a trailing newline completes normally', async () => {
  const updates = await collect([chunk({ content: '정상' }), 'data: [DONE]']);
  assert.equal(updates.at(-1).kind, 'done');
  assert.equal(updates.some((update) => update.kind === 'error'), false);
});

test('an upstream error retains its original diagnosis when the connection closes', async () => {
  const updates = await collect(['event: error\ndata: {"error":{"code":"UPSTREAM_TIMEOUT","message":"timeout"}}\n\n']);
  assert.equal(updates.length, 1);
  assert.equal(updates[0].code, 'UPSTREAM_TIMEOUT');
});
