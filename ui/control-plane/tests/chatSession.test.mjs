import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_CHAT_SETTINGS,
  applyChatUpdate,
  buildChatRequest,
  chatCapableModels,
  chatControls,
  completeFromResponse,
  createRequestContext,
  finishTurn,
  modelFeatureLabels,
  startTurn,
  stopTurn,
  turnFacts,
  turnNotice,
} from '../src/chatSession.ts';

const MAIN = {
  id: 'local-main',
  backend: 'vllm-cuda',
  capabilities: ['chat.completions', 'chat.completions.tools', 'responses'],
  input_modalities: ['text', 'image'],
  request_limits: { image: { max_inputs: 1, max_bytes: 25_000_000 } },
  request_parameters: {
    temperature: { type: 'number', min: 0, max: 2 },
    max_tokens: { type: 'integer', min: 1, max: 4096, aliases: ['max_completion_tokens'] },
    stream: { type: 'boolean' },
    stream_options: { type: 'object' },
    reasoning: { type: 'boolean', default: false, mode: 'request_opt_in' },
    tools: { type: 'array', min_items: 1, max_items: 64 },
    response_format: { type: 'object', allowed_types: ['text', 'json_object', 'json_schema'] },
  },
};

function exchange(id, user, content, status = 'complete') {
  return {
    id,
    user,
    sentAtSeconds: 0,
    requestContext: createRequestContext(MAIN, { model: MAIN.id, messages: [] }),
    assistant: { ...startTurn(0), status, content },
  };
}

test('only chat-capable public models are offered', () => {
  const models = chatCapableModels([
    MAIN,
    { id: 'local-embed', backend: 'vllm-cuda', capabilities: ['embeddings'], request_parameters: {} },
  ]);
  assert.deepEqual(models.map((model) => model.id), ['local-main']);
});

test('model feature labels come from the public model contract', () => {
  assert.deepEqual(modelFeatureLabels(MAIN), [
    '텍스트',
    '이미지',
    '도구',
    '추론',
    '구조화 출력',
  ]);
  assert.deepEqual(modelFeatureLabels({
    ...MAIN,
    input_modalities: ['text', 'audio'],
    request_parameters: { stream: { type: 'boolean' } },
  }), ['텍스트', '오디오']);
});

test('send-time request context snapshots model contract and actual parameters', () => {
  const model = {
    ...MAIN,
    capabilities: [...MAIN.capabilities],
    input_modalities: [...MAIN.input_modalities],
  };
  const body = {
    model: MAIN.id,
    messages: [{ role: 'user', content: '안녕' }],
    temperature: 0.4,
    stream_options: { include_usage: true },
  };
  const context = createRequestContext(model, body);

  model.capabilities.push('future.capability');
  model.input_modalities.push('audio');
  body.stream_options.include_usage = false;

  assert.deepEqual(context, {
    modelId: 'local-main',
    backend: 'vllm-cuda',
    capabilities: ['chat.completions', 'chat.completions.tools', 'responses'],
    inputModalities: ['text', 'image'],
    parameters: {
      temperature: 0.4,
      stream_options: { include_usage: true },
    },
  });
});

test('the request carries only advertised parameters and omits model defaults', () => {
  const { body, error } = buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, [], '안녕');
  assert.equal(error, null);
  assert.deepEqual(body, {
    model: 'local-main',
    messages: [{ role: 'user', content: '안녕' }],
    stream: true,
    stream_options: { include_usage: true },
  });

  const bare = { ...MAIN, request_parameters: { stream: { type: 'boolean' } } };
  const settings = { ...DEFAULT_CHAT_SETTINGS, temperature: '0.3', maxTokens: '64', reasoning: true };
  assert.deepEqual(Object.keys(buildChatRequest(bare, settings, [], 'x').body).sort(), ['messages', 'model', 'stream']);
});

test('explicit settings are validated against the advertised range before sending', () => {
  const ok = buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, temperature: '0.7', maxTokens: '256', reasoning: true }, [], 'x');
  assert.equal(ok.error, null);
  assert.equal(ok.body.temperature, 0.7);
  assert.equal(ok.body.max_tokens, 256);
  assert.equal(ok.body.reasoning, true);

  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, maxTokens: '5000' }, [], 'x').error, /1–4096/);
  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, maxTokens: '1.5' }, [], 'x').error, /정수/);
  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, temperature: '3' }, [], 'x').error, /0–2/);
});

test('history keeps user and assistant turns alternating by dropping failed exchanges', () => {
  const history = [
    exchange(1, '첫 질문', '첫 답'),
    exchange(2, '실패한 질문', '', 'failed'),
    exchange(3, '중지한 질문', '부분 답', 'stopped'),
  ];
  const { body } = buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, systemPrompt: '짧게 답하세요.' }, history, '다음 질문');
  assert.deepEqual(body.messages.map((message) => message.role), ['system', 'user', 'assistant', 'user', 'assistant', 'user']);
  assert.deepEqual(body.messages.map((message) => message.content).slice(1), ['첫 질문', '첫 답', '중지한 질문', '부분 답', '다음 질문']);
});

test('reasoning control reflects the model default', () => {
  assert.deepEqual(chatControls(MAIN).reasoning, { defaultEnabled: false });
  assert.equal(chatControls({ ...MAIN, request_parameters: {} }).reasoning, null);
});

test('time to first token counts reasoning as the first produced token', () => {
  let turn = startTurn(1000);
  turn = applyChatUpdate(turn, { kind: 'chunk', content: '', reasoning: '', finishReason: null, usage: null }, 1100);
  assert.equal(turn.firstTokenAt, null, 'role-only chunk is not a token');
  turn = applyChatUpdate(turn, { kind: 'chunk', content: '', reasoning: '음', finishReason: null, usage: null }, 1250);
  turn = applyChatUpdate(turn, { kind: 'chunk', content: '답', reasoning: '', finishReason: 'stop', usage: null }, 1400);
  turn = applyChatUpdate(turn, {
    kind: 'chunk', content: '', reasoning: '', finishReason: null,
    usage: { prompt_tokens: 10, completion_tokens: 41, total_tokens: 51 },
  }, 3250);
  turn = applyChatUpdate(turn, { kind: 'done' }, 3250);

  assert.equal(turn.status, 'complete');
  assert.equal(turn.finishReason, 'stop');
  const facts = Object.fromEntries(turnFacts(turn).map((fact) => [fact.label, fact.value]));
  assert.equal(facts['첫 토큰'], '250ms');
  assert.equal(facts['전체'], '2.25초');
  assert.equal(facts['토큰'], '입력 10 · 출력 41');
  assert.equal(facts['생성 속도'], '20.0 tok/s');
});

test('a stream error after partial output fails the turn and later events are ignored', () => {
  let turn = startTurn(0);
  turn = applyChatUpdate(turn, { kind: 'chunk', content: '부분', reasoning: '', finishReason: null, usage: null }, 10);
  turn = applyChatUpdate(turn, { kind: 'error', code: 'UPSTREAM_TIMEOUT', message: '시간 초과', requestId: 'req_1' }, 20);
  turn = applyChatUpdate(turn, { kind: 'done' }, 30);
  assert.equal(turn.status, 'failed');
  assert.equal(turn.content, '부분');
  assert.deepEqual(turn.error, { code: 'UPSTREAM_TIMEOUT', message: '시간 초과' });
  assert.equal(turn.requestId, 'req_1');
  assert.equal(turn.finishedAt, 20);
});

test('operator notices explain truncated, stopped and reasoning-only answers', () => {
  const base = { ...startTurn(0), status: 'complete', finishedAt: 1 };
  assert.match(turnNotice({ ...base, content: '…', finishReason: 'length' }), /최대 출력 토큰/);
  assert.match(turnNotice({ ...base, content: '', reasoning: '생각만' }), /답변은 없습니다/);
  assert.match(turnNotice(stopTurn(startTurn(0), 5)), /중지했습니다/);
  assert.equal(turnNotice(finishTurn({ ...startTurn(0), content: '정상' }, 5)), null);
});

test('a non-streaming response reports total time without inventing a first-token time', () => {
  const turn = completeFromResponse(startTurn(0), {
    choices: [{ message: { content: '한 번에 온 답' }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 3, completion_tokens: 4, total_tokens: 7 },
  }, 900);
  assert.equal(turn.content, '한 번에 온 답');
  assert.deepEqual(turnFacts(turn).map((fact) => fact.label), ['전체', '토큰']);
});
