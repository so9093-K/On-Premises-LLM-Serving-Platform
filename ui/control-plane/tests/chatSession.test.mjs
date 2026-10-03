import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_CHAT_SETTINGS,
  applyChatUpdate,
  attachmentAccept,
  attachmentContentPart,
  buildChatRequest,
  chatCapableModels,
  chatControls,
  classifyAttachment,
  completeFromResponse,
  conversationAttachments,
  createRequestContext,
  finishTurn,
  modelFeatureLabels,
  numberControlRangeHint,
  startTurn,
  stopTurn,
  turnFacts,
  turnNotice,
  validateChatAttachments,
} from '../src/chatSession.ts';

const MAIN = {
  id: 'local-main',
  backend: 'vllm-cuda',
  capabilities: ['chat.completions', 'chat.completions.tools', 'responses'],
  input_modalities: ['text', 'image', 'audio', 'video'],
  request_limits: {
    image: {
      max_inputs: 1,
      max_bytes: 25_000_000,
      max_pixels: 12_845_056,
      allowed_mime_types: ['image/jpeg', 'image/png'],
      allowed_url_schemes: ['data'],
    },
    audio: {
      max_inputs: 1,
      max_bytes: 25_000_000,
      allowed_formats: ['wav', 'm4a'],
    },
    video: {
      max_inputs: 1,
      max_bytes: 50_000_000,
      allowed_mime_types: ['video/mp4', 'video/webm'],
      allowed_url_schemes: ['data'],
    },
  },
  request_parameters: {
    temperature: { type: 'number', min: 0, max: 2 },
    max_tokens: { type: 'integer', min: 1, max: 4096, aliases: ['max_completion_tokens'] },
    top_p: { type: 'number', min_exclusive: 0, max: 1 },
    top_k: { type: 'integer', min: -1 },
    min_p: { type: 'number', min: 0, max: 1 },
    presence_penalty: { type: 'number', min: -2, max: 2 },
    frequency_penalty: { type: 'number', min: -2, max: 2 },
    repetition_penalty: { type: 'number', min_exclusive: 0, max: 2 },
    stop: { type: 'string_or_string_array', max_items: 2 },
    seed: { type: 'integer', min: 0 },
    n: { type: 'integer', min: 1, max: 1 },
    stream: { type: 'boolean' },
    stream_options: { type: 'object' },
    reasoning: { type: 'boolean', default: false, mode: 'request_opt_in' },
    logprobs: { type: 'boolean', default: false, allow_stream: true },
    top_logprobs: { type: 'integer', min: 0, max: 10, requires: { logprobs: true } },
    tools: { type: 'array', min_items: 1, max_items: 64 },
    response_format: {
      type: 'object',
      allowed_types: ['text', 'json_object', 'json_schema'],
      json_object: { require_json_instruction: true },
      json_schema: {
        max_schema_bytes: 512,
        max_depth: 4,
        max_total_properties: 8,
        require_root_object: true,
        require_additional_properties_false: true,
        strict: { allowed: true, require_true: false },
      },
    },
  },
};

function exchange(id, user, content, status = 'complete') {
  return {
    id,
    user,
    attachments: [],
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
    '오디오',
    '비디오',
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
    inputModalities: ['text', 'image', 'audio', 'video'],
    parameters: {
      temperature: 0.4,
      stream_options: { include_usage: true },
    },
  });
});

test('numeric controls preserve inclusive and exclusive request boundaries', () => {
  const controls = chatControls(MAIN);
  assert.equal(numberControlRangeHint(controls.temperature), '0 이상 · 2 이하');
  assert.equal(numberControlRangeHint(controls.topP), '0 초과 · 1 이하');
  assert.equal(numberControlRangeHint(controls.repetitionPenalty), '0 초과 · 2 이하');

  assert.match(
    buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, topP: '0' }, [], 'x').error,
    /0 초과/,
  );
  assert.equal(
    buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, topP: '0.1' }, [], 'x').error,
    null,
  );
  assert.match(
    buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, repetitionPenalty: '0' }, [], 'x').error,
    /0 초과/,
  );
});

test('advanced scalar settings are serialized only when advertised and explicitly set', () => {
  const settings = {
    ...DEFAULT_CHAT_SETTINGS,
    temperature: '0.6',
    topP: '0.9',
    topK: '40',
    minP: '0.05',
    presencePenalty: '0.2',
    frequencyPenalty: '-0.1',
    repetitionPenalty: '1.1',
    stop: 'END\nDONE',
    seed: '7',
  };
  const { body, error } = buildChatRequest(MAIN, settings, [], 'x');
  assert.equal(error, null);
  assert.equal(body.temperature, 0.6);
  assert.equal(body.top_p, 0.9);
  assert.equal(body.top_k, 40);
  assert.equal(body.min_p, 0.05);
  assert.equal(body.presence_penalty, 0.2);
  assert.equal(body.frequency_penalty, -0.1);
  assert.equal(body.repetition_penalty, 1.1);
  assert.deepEqual(body.stop, ['END', 'DONE']);
  assert.equal(body.seed, 7);

  const tooManyStops = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, stop: 'A\nB\nC' },
    [],
    'x',
  );
  assert.match(tooManyStops.error, /최대 2개/);
});

test('streaming and logprobs dependencies follow the advertised contract', () => {
  const nonStreaming = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, stream: false },
    [],
    'x',
  );
  assert.equal(nonStreaming.error, null);
  assert.equal(nonStreaming.body.stream, false);
  assert.equal('stream_options' in nonStreaming.body, false);

  const missingRequirement = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, topLogprobs: '3' },
    [],
    'x',
  );
  assert.match(missingRequirement.error, /로그확률을 켜야/);

  const enabled = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, logprobs: true, topLogprobs: '3' },
    [],
    'x',
  );
  assert.equal(enabled.error, null);
  assert.equal(enabled.body.logprobs, true);
  assert.equal(enabled.body.top_logprobs, 3);

  const noStreamLogprobs = {
    ...MAIN,
    request_parameters: {
      ...MAIN.request_parameters,
      logprobs: { type: 'boolean', default: false, allow_stream: false },
    },
  };
  assert.match(
    buildChatRequest(noStreamLogprobs, { ...DEFAULT_CHAT_SETTINGS, logprobs: true }, [], 'x').error,
    /스트리밍 응답에서 로그확률/,
  );
});

test('fixed response count is presented as policy instead of becoming a duplicate knob', () => {
  assert.equal(chatControls(MAIN).fixedN, 1);
});

test('multimodal attachments follow public modalities and request limits', () => {
  assert.equal(attachmentAccept(MAIN), 'image/jpeg,image/png,.wav,.m4a,video/mp4,video/webm');
  assert.deepEqual(
    classifyAttachment(MAIN, { name: 'photo.jpg', mimeType: 'image/jpeg', sizeBytes: 100 }),
    { modality: 'image', error: null },
  );
  assert.deepEqual(
    classifyAttachment(MAIN, { name: 'sound.m4a', mimeType: 'audio/mp4', sizeBytes: 100 }),
    { modality: 'audio', audioFormat: 'm4a', error: null },
  );
  assert.match(
    classifyAttachment(MAIN, { name: 'bad.txt', mimeType: 'text/plain', sizeBytes: 1 }).error,
    /인식할 수 있는/,
  );

  const tooLarge = {
    id: 'large',
    name: 'large.png',
    modality: 'image',
    mimeType: 'image/png',
    sizeBytes: 25_000_001,
    data: 'data:image/png;base64,AAAA',
  };
  assert.match(validateChatAttachments(MAIN, [tooLarge]), /25,000,000바이트/);
});

test('multimodal content parts use the Gateway Chat contract exactly', () => {
  const image = {
    id: 'image',
    name: 'photo.jpg',
    modality: 'image',
    mimeType: 'image/jpeg',
    sizeBytes: 4,
    data: 'data:image/jpeg;base64,AAAA',
  };
  const audio = {
    id: 'audio',
    name: 'tone.wav',
    modality: 'audio',
    mimeType: 'audio/wav',
    sizeBytes: 4,
    data: 'AAAA',
    audioFormat: 'wav',
  };
  const video = {
    id: 'video',
    name: 'clip.mp4',
    modality: 'video',
    mimeType: 'video/mp4',
    sizeBytes: 4,
    data: 'data:video/mp4;base64,AAAA',
  };
  assert.deepEqual(attachmentContentPart(image), {
    type: 'image_url',
    image_url: { url: image.data },
  });
  assert.deepEqual(attachmentContentPart(audio), {
    type: 'input_audio',
    input_audio: { data: 'AAAA', format: 'wav' },
  });
  assert.deepEqual(attachmentContentPart(video), {
    type: 'video_url',
    video_url: { url: video.data },
  });

  const request = buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, [], '설명해줘', [image, audio, video]);
  assert.equal(request.error, null);
  assert.deepEqual(request.body.messages[0].content, [
    { type: 'text', text: '설명해줘' },
    { type: 'image_url', image_url: { url: image.data } },
    { type: 'input_audio', input_audio: { data: 'AAAA', format: 'wav' } },
    { type: 'video_url', video_url: { url: video.data } },
  ]);
});

test('attachment limits count successful conversation history across the whole request', () => {
  const image = {
    id: 'image',
    name: 'photo.jpg',
    modality: 'image',
    mimeType: 'image/jpeg',
    sizeBytes: 4,
    data: 'data:image/jpeg;base64,AAAA',
  };
  const history = [{
    ...exchange(1, '첫 이미지', '봤습니다'),
    attachments: [image],
  }];
  assert.deepEqual(conversationAttachments(history), [image]);

  const repeated = buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, history, '다음 이미지', [
    { ...image, id: 'image-2', name: 'photo-2.jpg' },
  ]);
  assert.match(repeated.error, /요청 전체에서 최대 1개/);

  const followup = buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, history, '이미지에 대해 더 말해줘');
  assert.equal(followup.error, null);
  assert.deepEqual(followup.body.messages[0].content, [
    { type: 'text', text: '첫 이미지' },
    { type: 'image_url', image_url: { url: image.data } },
  ]);
});

test('attachment-only user turns are valid while empty turns are rejected', () => {
  const image = {
    id: 'image',
    name: 'photo.jpg',
    modality: 'image',
    mimeType: 'image/jpeg',
    sizeBytes: 4,
    data: 'data:image/jpeg;base64,AAAA',
  };
  const withAttachment = buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, [], '', [image]);
  assert.equal(withAttachment.error, null);
  assert.deepEqual(withAttachment.body.messages[0].content, [
    { type: 'image_url', image_url: { url: image.data } },
  ]);
  assert.match(buildChatRequest(MAIN, DEFAULT_CHAT_SETTINGS, [], '').error, /메시지나 첨부 파일/);
});

test('structured output follows advertised types and json-object instruction policy', () => {
  const missing = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, responseFormat: 'json_object' },
    [],
    '평문으로 답해줘',
  );
  assert.match(missing.error, /JSON 지시문/);

  const jsonObject = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, responseFormat: 'json_object' },
    [],
    'Return JSON with one field.',
  );
  assert.equal(jsonObject.error, null);
  assert.deepEqual(jsonObject.body.response_format, { type: 'json_object' });

  const text = buildChatRequest(
    MAIN,
    { ...DEFAULT_CHAT_SETTINGS, responseFormat: 'text' },
    [],
    'hello',
  );
  assert.deepEqual(text.body.response_format, { type: 'text' });
});

test('json-schema output preflights public high-level limits and serializes OpenAI shape', () => {
  const schema = {
    type: 'object',
    additionalProperties: false,
    properties: { answer: { type: 'string' } },
    required: ['answer'],
  };
  const ok = buildChatRequest(
    MAIN,
    {
      ...DEFAULT_CHAT_SETTINGS,
      responseFormat: 'json_schema',
      jsonSchemaName: 'answer_schema',
      jsonSchemaText: JSON.stringify(schema),
      jsonSchemaStrict: true,
    },
    [],
    '답을 만들어줘',
  );
  assert.equal(ok.error, null);
  assert.deepEqual(ok.body.response_format, {
    type: 'json_schema',
    json_schema: {
      name: 'answer_schema',
      strict: true,
      schema,
    },
  });

  assert.match(buildChatRequest(
    MAIN,
    {
      ...DEFAULT_CHAT_SETTINGS,
      responseFormat: 'json_schema',
      jsonSchemaName: '',
      jsonSchemaText: JSON.stringify(schema),
    },
    [],
    'x',
  ).error, /이름/);

  assert.match(buildChatRequest(
    MAIN,
    {
      ...DEFAULT_CHAT_SETTINGS,
      responseFormat: 'json_schema',
      jsonSchemaText: JSON.stringify({ type: 'array', items: { type: 'string' } }),
    },
    [],
    'x',
  ).error, /root type/);

  assert.match(buildChatRequest(
    MAIN,
    {
      ...DEFAULT_CHAT_SETTINGS,
      responseFormat: 'json_schema',
      jsonSchemaText: JSON.stringify({
        type: 'object',
        properties: { answer: { type: 'string' } },
        required: ['answer'],
      }),
    },
    [],
    'x',
  ).error, /additionalProperties:false/);

  const defaultStrict = buildChatRequest(
    MAIN,
    {
      ...DEFAULT_CHAT_SETTINGS,
      responseFormat: 'json_schema',
      jsonSchemaName: 'answer_schema',
      jsonSchemaText: JSON.stringify(schema),
    },
    [],
    'x',
  );
  assert.equal(defaultStrict.error, null);
  assert.equal('strict' in defaultStrict.body.response_format.json_schema, false);
});

test('structured output ignores unknown future format names instead of reinterpreting them', () => {
  const future = {
    ...MAIN,
    request_parameters: {
      ...MAIN.request_parameters,
      response_format: {
        ...MAIN.request_parameters.response_format,
        allowed_types: ['text', 'future_format'],
      },
    },
  };
  assert.deepEqual(chatControls(future).responseFormat.allowedTypes, ['text']);
  assert.match(
    buildChatRequest(
      future,
      { ...DEFAULT_CHAT_SETTINGS, responseFormat: 'future_format' },
      [],
      'x',
    ).error,
    /광고하지 않은 응답 형식/,
  );
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

  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, maxTokens: '5000' }, [], 'x').error, /1 이상 · 4096 이하/);
  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, maxTokens: '1.5' }, [], 'x').error, /정수/);
  assert.match(buildChatRequest(MAIN, { ...DEFAULT_CHAT_SETTINGS, temperature: '3' }, [], 'x').error, /0 이상 · 2 이하/);
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
  assert.deepEqual(chatControls(MAIN).reasoning, {
    defaultEnabled: false,
    constValue: null,
    allowStream: null,
  });
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
