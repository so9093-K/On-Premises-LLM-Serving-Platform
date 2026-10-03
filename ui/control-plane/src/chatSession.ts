// 채팅 테스트 화면의 순수 로직. 요청 본문은 /v1/models가 광고한 request_parameters
// 안에서만 만들고, 응답 누적과 지연 측정은 화면과 분리해 테스트한다.
import type { ChatStreamUpdate, ChatToolCallDelta, ChatUsage } from './chatStream';

type ParameterSpec = Record<string, unknown>;

export type PublicModel = {
  id: string;
  backend: string;
  capabilities: readonly string[];
  input_modalities?: readonly string[];
  request_limits?: Record<string, ParameterSpec>;
  request_parameters: Record<string, ParameterSpec>;
};

export type NumericBound = { value: number; exclusive: boolean };

export type NumberControl = {
  minimum: NumericBound | null;
  maximum: NumericBound | null;
  integer: boolean;
  requires: Record<string, unknown>;
};

export type BooleanControl = {
  defaultEnabled: boolean | null;
  constValue: boolean | null;
  allowStream: boolean | null;
};

export type StringListControl = {
  maxItems: number | null;
};

export type ToolControl = {
  minItems: number | null;
  maxItems: number | null;
  choiceAllowed: string[];
  allowNamed: boolean;
  parallelConst: boolean | null;
};

export type ToolDraft = {
  id: string;
  name: string;
  description: string;
  parametersText: string;
  strict: boolean | null;
};

export type ChatToolCall = {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
};

export type ChatToolResult = {
  toolCallId: string;
  content: string;
};

export const TOOL_CHOICE_DEFAULT = '__default__';
export const TOOL_CHOICE_NAMED = '__named__';

export type ResponseFormatType = 'text' | 'json_object' | 'json_schema';

export type ResponseFormatControl = {
  allowedTypes: ResponseFormatType[];
  requireJsonInstruction: boolean;
  jsonSchema: {
    maxSchemaBytes: number | null;
    maxDepth: number | null;
    maxTotalProperties: number | null;
    requireRootObject: boolean;
    requireAdditionalPropertiesFalse: boolean;
    strictAllowed: boolean;
    strictRequireTrue: boolean;
  } | null;
};

export type ChatControls = {
  temperature: NumberControl | null;
  maxTokens: NumberControl | null;
  topP: NumberControl | null;
  topK: NumberControl | null;
  minP: NumberControl | null;
  presencePenalty: NumberControl | null;
  frequencyPenalty: NumberControl | null;
  repetitionPenalty: NumberControl | null;
  seed: NumberControl | null;
  topLogprobs: NumberControl | null;
  stop: StringListControl | null;
  reasoning: BooleanControl | null;
  stream: BooleanControl | null;
  logprobs: BooleanControl | null;
  tools: ToolControl | null;
  responseFormat: ResponseFormatControl | null;
  includeUsage: boolean;
  fixedN: number | null;
};

export type ChatSettings = {
  systemPrompt: string;
  temperature: string;
  maxTokens: string;
  topP: string;
  topK: string;
  minP: string;
  presencePenalty: string;
  frequencyPenalty: string;
  repetitionPenalty: string;
  stop: string;
  seed: string;
  topLogprobs: string;
  reasoning: boolean | null;
  stream: boolean;
  logprobs: boolean | null;
  responseFormat: 'default' | ResponseFormatType;
  jsonSchemaName: string;
  jsonSchemaText: string;
  jsonSchemaStrict: boolean | null;
  toolDrafts: ToolDraft[];
  toolChoice: string;
  toolChoiceName: string;
};

export type TurnStatus = 'streaming' | 'complete' | 'stopped' | 'failed';

export type AssistantTurn = {
  status: TurnStatus;
  content: string;
  reasoning: string;
  toolCalls: ChatToolCall[];
  finishReason: string | null;
  usage: ChatUsage | null;
  error: { code: string | null; message: string } | null;
  requestId: string | null;
  startedAt: number;
  firstTokenAt: number | null;
  finishedAt: number | null;
};

export type ChatRequestContext = {
  modelId: string;
  backend: string;
  capabilities: string[];
  inputModalities: string[];
  parameters: Record<string, unknown>;
};

export type ChatAttachmentModality = 'image' | 'audio' | 'video';

export type ChatAttachment = {
  id: string;
  name: string;
  modality: ChatAttachmentModality;
  mimeType: string;
  sizeBytes: number;
  data: string;
  audioFormat?: string;
  width?: number;
  height?: number;
};

export type Exchange = {
  id: number;
  user: string;
  attachments: ChatAttachment[];
  toolResults?: ChatToolResult[];
  sentAtSeconds: number;
  requestContext: ChatRequestContext;
  assistant: AssistantTurn;
};

export type ChatContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }
  | { type: 'input_audio'; input_audio: { data: string; format: string } }
  | { type: 'video_url'; video_url: { url: string } };

export type ChatMessage =
  | { role: 'system' | 'user'; content: string | ChatContentPart[] }
  | { role: 'assistant'; content: string | null; tool_calls?: ChatToolCall[] }
  | { role: 'tool'; content: string; tool_call_id: string };

export function chatCapableModels(models: readonly PublicModel[]): PublicModel[] {
  return models.filter((model) => model.capabilities.includes('chat.completions'));
}

const INPUT_MODALITY_LABELS: Record<string, string> = {
  text: '텍스트',
  image: '이미지',
  audio: '오디오',
  video: '비디오',
};

export function inputModalityLabel(value: string): string {
  return INPUT_MODALITY_LABELS[value] ?? value;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function mediaLimit(model: PublicModel, modality: ChatAttachmentModality): Record<string, unknown> {
  return objectOrEmpty(model.request_limits?.[modality]);
}

function fileExtension(name: string): string {
  const index = name.lastIndexOf('.');
  return index < 0 ? '' : name.slice(index + 1).toLowerCase();
}

export function attachmentAccept(model: PublicModel): string {
  const accepted: string[] = [];
  const modalities = new Set(model.input_modalities ?? []);
  if (modalities.has('image')) {
    const values = stringList(mediaLimit(model, 'image').allowed_mime_types);
    accepted.push(...(values.length > 0 ? values : ['image/*']));
  }
  if (modalities.has('audio')) {
    const values = stringList(mediaLimit(model, 'audio').allowed_formats);
    accepted.push(...(values.length > 0 ? values.map((value) => `.${value}`) : ['audio/*']));
  }
  if (modalities.has('video')) {
    const values = stringList(mediaLimit(model, 'video').allowed_mime_types);
    accepted.push(...(values.length > 0 ? values : ['video/*']));
  }
  return [...new Set(accepted)].join(',');
}

export function classifyAttachment(
  model: PublicModel,
  candidate: { name: string; mimeType: string; sizeBytes: number },
): { modality: ChatAttachmentModality; audioFormat?: string; error: null } | { error: string } {
  const mimeType = candidate.mimeType.toLowerCase();
  const extension = fileExtension(candidate.name);
  let modality: ChatAttachmentModality | null = null;
  if (mimeType.startsWith('image/')) modality = 'image';
  else if (mimeType.startsWith('video/')) modality = 'video';
  else if (mimeType.startsWith('audio/')) modality = 'audio';
  else if (stringList(mediaLimit(model, 'audio').allowed_formats).includes(extension)) modality = 'audio';

  if (modality === null) return { error: '현재 모델 계약에서 인식할 수 있는 이미지·오디오·비디오 파일이 아닙니다.' };
  if (!(model.input_modalities ?? []).includes(modality)) {
    return { error: `현재 모델은 ${inputModalityLabel(modality)} 입력을 지원하지 않습니다.` };
  }
  const limit = mediaLimit(model, modality);
  const maxBytes = finite(limit.max_bytes);
  if (maxBytes !== null && candidate.sizeBytes > maxBytes) {
    return { error: `${inputModalityLabel(modality)} 파일은 ${maxBytes.toLocaleString('ko-KR')}바이트 이하여야 합니다.` };
  }
  if (modality === 'audio') {
    const allowed = stringList(limit.allowed_formats);
    if (!extension || (allowed.length > 0 && !allowed.includes(extension))) {
      return { error: `오디오는 ${allowed.join(', ') || '현재 모델이 광고한 형식'}만 사용할 수 있습니다.` };
    }
    return { modality, audioFormat: extension, error: null };
  }
  const allowedMimeTypes = stringList(limit.allowed_mime_types);
  if (!mimeType || (allowedMimeTypes.length > 0 && !allowedMimeTypes.includes(mimeType))) {
    return { error: `${inputModalityLabel(modality)} MIME 형식이 현재 모델 계약에 없습니다.` };
  }
  return { modality, error: null };
}

export function validateChatAttachments(
  model: PublicModel,
  attachments: readonly ChatAttachment[],
): string | null {
  const counts: Record<ChatAttachmentModality, number> = { image: 0, audio: 0, video: 0 };
  for (const attachment of attachments) {
    const classified = classifyAttachment(model, {
      name: attachment.name,
      mimeType: attachment.mimeType,
      sizeBytes: attachment.sizeBytes,
    });
    if (!('modality' in classified)) return classified.error;
    if (classified.modality !== attachment.modality) return '첨부 파일 modality가 현재 모델 계약과 일치하지 않습니다.';
    if (attachment.modality === 'audio' && classified.audioFormat !== attachment.audioFormat) {
      return '오디오 형식이 현재 모델 계약과 일치하지 않습니다.';
    }
    if (attachment.modality === 'image') {
      const maxPixels = finite(mediaLimit(model, 'image').max_pixels);
      if (
        maxPixels !== null
        && attachment.width !== undefined
        && attachment.height !== undefined
        && attachment.width * attachment.height > maxPixels
      ) {
        return `이미지는 최대 ${maxPixels.toLocaleString('ko-KR')}픽셀까지 사용할 수 있습니다.`;
      }
    }
    counts[attachment.modality] += 1;
  }
  for (const modality of ['image', 'audio', 'video'] as const) {
    const maxInputs = integerOrNull(mediaLimit(model, modality).max_inputs);
    if (maxInputs !== null && counts[modality] > maxInputs) {
      return `${inputModalityLabel(modality)} 입력은 요청 전체에서 최대 ${maxInputs}개까지 사용할 수 있습니다.`;
    }
  }
  return null;
}

export function attachmentContentPart(attachment: ChatAttachment): ChatContentPart {
  if (attachment.modality === 'image') {
    return { type: 'image_url', image_url: { url: attachment.data } };
  }
  if (attachment.modality === 'video') {
    return { type: 'video_url', video_url: { url: attachment.data } };
  }
  return {
    type: 'input_audio',
    input_audio: { data: attachment.data, format: attachment.audioFormat ?? '' },
  };
}

function userMessageContent(text: string, attachments: readonly ChatAttachment[]): string | ChatContentPart[] {
  if (attachments.length === 0) return text;
  const parts: ChatContentPart[] = [];
  if (text) parts.push({ type: 'text', text });
  parts.push(...attachments.map(attachmentContentPart));
  return parts;
}

function exchangeIncludedInHistory(exchange: Exchange): boolean {
  const turn = exchange.assistant;
  if (turn.status === 'failed') return false;
  if (turn.toolCalls.length > 0) {
    return turn.status === 'complete'
      && turn.finishReason === 'tool_calls'
      && turn.toolCalls.every((call) => call.id !== '' && call.function.name !== '');
  }
  return turn.content !== '';
}

function toolResultsResolveSource(source: Exchange, candidate: Exchange): boolean {
  if (candidate.id <= source.id || !exchangeIncludedInHistory(candidate)) return false;
  const callIds = new Set(source.assistant.toolCalls.map((call) => call.id));
  const results = candidate.toolResults ?? [];
  if (callIds.size === 0 || results.length !== callIds.size) return false;
  const resultIds = new Set(results.map((result) => result.toolCallId));
  return resultIds.size === callIds.size && [...callIds].every((id) => resultIds.has(id));
}

export function pendingToolCallExchange(exchanges: readonly Exchange[]): Exchange | null {
  for (const exchange of exchanges) {
    if (
      exchange.assistant.toolCalls.length > 0
      && exchangeIncludedInHistory(exchange)
      && !exchanges.some((candidate) => toolResultsResolveSource(exchange, candidate))
    ) {
      return exchange;
    }
  }
  return null;
}

export function conversationAttachments(exchanges: readonly Exchange[]): ChatAttachment[] {
  return exchanges
    .filter(exchangeIncludedInHistory)
    .flatMap((exchange) => exchange.attachments);
}

export function modelFeatureLabels(model: PublicModel): string[] {
  const labels = (model.input_modalities ?? []).map(inputModalityLabel);
  const params = model.request_parameters;
  if (params.tools !== undefined) labels.push('도구');
  if (params.reasoning !== undefined) labels.push('추론');
  const responseFormat = params.response_format;
  const allowedTypes = Array.isArray(responseFormat?.allowed_types)
    ? responseFormat.allowed_types
    : [];
  if (allowedTypes.some((value) => value === 'json_object' || value === 'json_schema')) {
    labels.push('구조화 출력');
  }
  return [...new Set(labels)];
}

function jsonSnapshot(value: Record<string, unknown>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

export function createRequestContext(
  model: PublicModel,
  body: Record<string, unknown>,
): ChatRequestContext {
  const parameters = Object.fromEntries(
    Object.entries(body).filter(([name]) => name !== 'model' && name !== 'messages'),
  );
  return {
    modelId: model.id,
    backend: model.backend,
    capabilities: [...model.capabilities],
    inputModalities: [...(model.input_modalities ?? [])],
    parameters: jsonSnapshot(parameters),
  };
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function integerOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

function objectOrEmpty(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function numericBound(
  inclusive: unknown,
  exclusive: unknown,
): NumericBound | null {
  const exclusiveValue = finite(exclusive);
  if (exclusiveValue !== null) return { value: exclusiveValue, exclusive: true };
  const inclusiveValue = finite(inclusive);
  return inclusiveValue === null ? null : { value: inclusiveValue, exclusive: false };
}

function numberControl(spec: ParameterSpec | undefined, integer: boolean): NumberControl | null {
  if (spec === undefined) return null;
  return {
    minimum: numericBound(spec.min, spec.min_exclusive),
    maximum: numericBound(spec.max, spec.max_exclusive),
    integer,
    requires: objectOrEmpty(spec.requires),
  };
}

function booleanControl(spec: ParameterSpec | undefined): BooleanControl | null {
  if (spec === undefined) return null;
  return {
    defaultEnabled: typeof spec.default === 'boolean' ? spec.default : null,
    constValue: typeof spec.const === 'boolean' ? spec.const : null,
    allowStream: typeof spec.allow_stream === 'boolean' ? spec.allow_stream : null,
  };
}

function stringListControl(spec: ParameterSpec | undefined): StringListControl | null {
  if (spec === undefined) return null;
  return { maxItems: integerOrNull(spec.max_items) };
}

function fixedNumericValue(spec: ParameterSpec | undefined): number | null {
  if (spec === undefined) return null;
  const min = finite(spec.min);
  const max = finite(spec.max);
  return min !== null && max !== null && min === max ? min : null;
}

function toolControl(params: Record<string, ParameterSpec>): ToolControl | null {
  const tools = params.tools;
  if (tools === undefined) return null;
  const choice = objectOrEmpty(params.tool_choice);
  const parallel = params.parallel_tool_calls;
  return {
    minItems: integerOrNull(tools.min_items),
    maxItems: integerOrNull(tools.max_items),
    choiceAllowed: stringList(choice.allowed),
    allowNamed: choice.allow_named === true,
    parallelConst: typeof parallel?.const === 'boolean' ? parallel.const : null,
  };
}

function responseFormatControl(spec: ParameterSpec | undefined): ResponseFormatControl | null {
  if (spec === undefined) return null;
  const allowedTypes = stringList(spec.allowed_types).filter(
    (value): value is ResponseFormatType => (
      value === 'text' || value === 'json_object' || value === 'json_schema'
    ),
  );
  const jsonObject = objectOrEmpty(spec.json_object);
  const schema = objectOrEmpty(spec.json_schema);
  const strict = objectOrEmpty(schema.strict);
  const schemaEnabled = allowedTypes.includes('json_schema');
  return {
    allowedTypes,
    requireJsonInstruction: jsonObject.require_json_instruction === true,
    jsonSchema: schemaEnabled ? {
      maxSchemaBytes: integerOrNull(schema.max_schema_bytes),
      maxDepth: integerOrNull(schema.max_depth),
      maxTotalProperties: integerOrNull(schema.max_total_properties),
      requireRootObject: schema.require_root_object === true,
      requireAdditionalPropertiesFalse: schema.require_additional_properties_false === true,
      strictAllowed: strict.allowed !== false,
      strictRequireTrue: strict.require_true === true,
    } : null,
  };
}

export function numberControlRangeHint(control: NumberControl): string {
  const parts: string[] = [];
  if (control.minimum) {
    parts.push(`${control.minimum.value} ${control.minimum.exclusive ? '초과' : '이상'}`);
  }
  if (control.maximum) {
    parts.push(`${control.maximum.value} ${control.maximum.exclusive ? '미만' : '이하'}`);
  }
  return parts.length > 0 ? parts.join(' · ') : '제한 없음';
}

export function chatControls(model: PublicModel): ChatControls {
  const params = model.request_parameters;
  return {
    temperature: numberControl(params.temperature, false),
    maxTokens: numberControl(params.max_tokens, true),
    topP: numberControl(params.top_p, false),
    topK: numberControl(params.top_k, true),
    minP: numberControl(params.min_p, false),
    presencePenalty: numberControl(params.presence_penalty, false),
    frequencyPenalty: numberControl(params.frequency_penalty, false),
    repetitionPenalty: numberControl(params.repetition_penalty, false),
    seed: numberControl(params.seed, true),
    topLogprobs: numberControl(params.top_logprobs, true),
    stop: stringListControl(params.stop),
    reasoning: booleanControl(params.reasoning),
    stream: booleanControl(params.stream),
    logprobs: booleanControl(params.logprobs),
    tools: toolControl(params),
    responseFormat: responseFormatControl(params.response_format),
    includeUsage: params.stream_options !== undefined,
    fixedN: fixedNumericValue(params.n),
  };
}

// 빈 문자열과 null은 "모델 기본값"이다. stream은 기존 Console의 streaming-first UX를
// 유지하되 사용자가 명시적으로 끌 수 있다.
export const DEFAULT_CHAT_SETTINGS: ChatSettings = {
  systemPrompt: '',
  temperature: '',
  maxTokens: '',
  topP: '',
  topK: '',
  minP: '',
  presencePenalty: '',
  frequencyPenalty: '',
  repetitionPenalty: '',
  stop: '',
  seed: '',
  topLogprobs: '',
  reasoning: null,
  stream: true,
  logprobs: null,
  responseFormat: 'default',
  jsonSchemaName: 'response',
  jsonSchemaText: '',
  jsonSchemaStrict: null,
  toolDrafts: [],
  toolChoice: TOOL_CHOICE_DEFAULT,
  toolChoiceName: '',
};

function boundViolated(value: number, bound: NumericBound, minimum: boolean): boolean {
  if (minimum) return bound.exclusive ? value <= bound.value : value < bound.value;
  return bound.exclusive ? value >= bound.value : value > bound.value;
}

function parseControlValue(
  raw: string,
  control: NumberControl,
  label: string,
): { value: number | null; error: string | null } {
  const trimmed = raw.trim();
  if (trimmed === '') return { value: null, error: null };
  const value = Number(trimmed);
  if (!Number.isFinite(value) || (control.integer && !Number.isInteger(value))) {
    return { value: null, error: `${label}은(는) ${control.integer ? '정수' : '숫자'}여야 합니다.` };
  }
  if (
    (control.minimum && boundViolated(value, control.minimum, true))
    || (control.maximum && boundViolated(value, control.maximum, false))
  ) {
    return {
      value: null,
      error: `${label}은(는) ${numberControlRangeHint(control)} 범위여야 합니다.`,
    };
  }
  return { value, error: null };
}

function parseStopValue(
  raw: string,
  control: StringListControl,
): { value: string | string[] | null; error: string | null } {
  if (raw === '') return { value: null, error: null };
  const values = raw.split('\n').filter((value) => value !== '');
  if (values.length === 0) return { value: null, error: null };
  if (control.maxItems !== null && values.length > control.maxItems) {
    return { value: null, error: `중지 문자열은 최대 ${control.maxItems}개까지 사용할 수 있습니다.` };
  }
  return { value: values.length === 1 ? values[0] : values, error: null };
}

function toolRequestParameters(
  control: ToolControl | null,
  settings: ChatSettings,
): { value: Record<string, unknown>; error: string | null } {
  const hasDrafts = settings.toolDrafts.length > 0;
  const hasChoice = settings.toolChoice !== TOOL_CHOICE_DEFAULT;
  if (control === null) {
    return hasDrafts || hasChoice
      ? { value: {}, error: '현재 모델은 도구 호출을 광고하지 않습니다.' }
      : { value: {}, error: null };
  }
  if (control.maxItems !== null && settings.toolDrafts.length > control.maxItems) {
    return { value: {}, error: `도구는 최대 ${control.maxItems}개까지 사용할 수 있습니다.` };
  }
  if (
    settings.toolDrafts.length > 0
    && control.minItems !== null
    && settings.toolDrafts.length < control.minItems
  ) {
    return { value: {}, error: `도구를 사용하려면 최소 ${control.minItems}개를 정의해야 합니다.` };
  }

  const tools: Record<string, unknown>[] = [];
  for (const [index, draft] of settings.toolDrafts.entries()) {
    const name = draft.name.trim();
    if (!name) return { value: {}, error: `도구 ${index + 1}의 function 이름을 입력하세요.` };
    const fn: Record<string, unknown> = { name };
    if (draft.description.trim()) fn.description = draft.description.trim();
    if (draft.parametersText.trim()) {
      let parameters: unknown;
      try {
        parameters = JSON.parse(draft.parametersText);
      } catch {
        return { value: {}, error: `도구 ${name}의 parameters가 유효한 JSON이 아닙니다.` };
      }
      if (typeof parameters !== 'object' || parameters === null || Array.isArray(parameters)) {
        return { value: {}, error: `도구 ${name}의 parameters는 JSON object여야 합니다.` };
      }
      fn.parameters = parameters;
    }
    if (draft.strict !== null) fn.strict = draft.strict;
    tools.push({ type: 'function', function: fn });
  }

  const value: Record<string, unknown> = {};
  if (tools.length > 0) value.tools = tools;
  if (settings.toolChoice === TOOL_CHOICE_NAMED) {
    if (!control.allowNamed) return { value: {}, error: '현재 모델은 named tool choice를 광고하지 않습니다.' };
    const name = settings.toolChoiceName.trim();
    if (!name) return { value: {}, error: '고정할 function을 선택하세요.' };
    if (!settings.toolDrafts.some((draft) => draft.name.trim() === name)) {
      return { value: {}, error: 'Named tool choice는 현재 정의한 function 중에서 선택해야 합니다.' };
    }
    value.tool_choice = { type: 'function', function: { name } };
  } else if (settings.toolChoice !== TOOL_CHOICE_DEFAULT) {
    if (!control.choiceAllowed.includes(settings.toolChoice)) {
      return { value: {}, error: '현재 모델이 광고하지 않은 tool_choice입니다.' };
    }
    if (settings.toolChoice !== 'none' && tools.length === 0) {
      return { value: {}, error: '이 tool_choice를 사용하려면 하나 이상의 도구를 정의해야 합니다.' };
    }
    value.tool_choice = settings.toolChoice;
  }
  return { value, error: null };
}

const SCHEMA_VALUE_KEYS = new Set([
  'additionalProperties', 'items', 'contains', 'propertyNames',
  'unevaluatedItems', 'unevaluatedProperties', 'if', 'then', 'else', 'not',
]);
const SCHEMA_ARRAY_KEYS = new Set(['anyOf', 'oneOf', 'allOf', 'prefixItems']);
const SCHEMA_MAP_KEYS = new Set([
  'properties', '$defs', 'definitions', 'dependentSchemas', 'patternProperties',
]);

function schemaChildren(value: Record<string, unknown>): Record<string, unknown>[] {
  const children: Record<string, unknown>[] = [];
  for (const [key, item] of Object.entries(value)) {
    if (SCHEMA_VALUE_KEYS.has(key) && typeof item === 'object' && item !== null && !Array.isArray(item)) {
      children.push(item as Record<string, unknown>);
    } else if (SCHEMA_ARRAY_KEYS.has(key) && Array.isArray(item)) {
      for (const child of item) {
        if (typeof child === 'object' && child !== null && !Array.isArray(child)) {
          children.push(child as Record<string, unknown>);
        }
      }
    } else if (SCHEMA_MAP_KEYS.has(key) && typeof item === 'object' && item !== null && !Array.isArray(item)) {
      for (const child of Object.values(item as Record<string, unknown>)) {
        if (typeof child === 'object' && child !== null && !Array.isArray(child)) {
          children.push(child as Record<string, unknown>);
        }
      }
    }
  }
  return children;
}

function schemaObjects(root: Record<string, unknown>): Record<string, unknown>[] {
  const result: Record<string, unknown>[] = [root];
  for (let index = 0; index < result.length; index += 1) {
    result.push(...schemaChildren(result[index]));
  }
  return result;
}

function schemaDepth(value: Record<string, unknown>): number {
  const children = schemaChildren(value);
  return 1 + (children.length === 0 ? 0 : Math.max(...children.map(schemaDepth)));
}

function totalSchemaProperties(value: Record<string, unknown>): number {
  return schemaObjects(value).reduce((total, item) => (
    total + (typeof item.properties === 'object' && item.properties !== null && !Array.isArray(item.properties)
      ? Object.keys(item.properties).length
      : 0)
  ), 0);
}

function messagesContainJsonInstruction(messages: readonly ChatMessage[]): boolean {
  return messages.some((message) => {
    if (typeof message.content === 'string') return message.content.toLowerCase().includes('json');
    if (!Array.isArray(message.content)) return false;
    return message.content.some((part) => part.type === 'text' && part.text.toLowerCase().includes('json'));
  });
}

function structuredResponseFormat(
  control: ResponseFormatControl,
  settings: ChatSettings,
  messages: readonly ChatMessage[],
): { value: Record<string, unknown> | null; error: string | null } {
  if (settings.responseFormat === 'default') return { value: null, error: null };
  if (!control.allowedTypes.includes(settings.responseFormat)) {
    return { value: null, error: '현재 모델이 광고하지 않은 응답 형식입니다.' };
  }
  if (settings.responseFormat === 'text') return { value: { type: 'text' }, error: null };
  if (settings.responseFormat === 'json_object') {
    if (control.requireJsonInstruction && !messagesContainJsonInstruction(messages)) {
      return { value: null, error: 'JSON object 모드는 메시지나 시스템 프롬프트에 JSON 지시문이 필요합니다.' };
    }
    return { value: { type: 'json_object' }, error: null };
  }

  const policy = control.jsonSchema;
  if (!policy) return { value: null, error: '현재 모델은 JSON Schema 출력을 광고하지 않습니다.' };
  const name = settings.jsonSchemaName.trim();
  if (!name) {
    return { value: null, error: 'JSON Schema 이름을 입력하세요.' };
  }
  let schema: unknown;
  try {
    schema = JSON.parse(settings.jsonSchemaText);
  } catch {
    return { value: null, error: 'JSON Schema가 유효한 JSON이 아닙니다.' };
  }
  if (typeof schema !== 'object' || schema === null || Array.isArray(schema)) {
    return { value: null, error: 'JSON Schema는 object여야 합니다.' };
  }
  const schemaObject = schema as Record<string, unknown>;
  const encodedBytes = new TextEncoder().encode(JSON.stringify(schemaObject)).length;
  if (policy.maxSchemaBytes !== null && encodedBytes > policy.maxSchemaBytes) {
    return { value: null, error: `JSON Schema는 ${policy.maxSchemaBytes.toLocaleString('ko-KR')}바이트 이하여야 합니다.` };
  }
  if (policy.maxDepth !== null && schemaDepth(schemaObject) > policy.maxDepth) {
    return { value: null, error: `JSON Schema depth는 ${policy.maxDepth} 이하여야 합니다.` };
  }
  if (
    policy.maxTotalProperties !== null
    && totalSchemaProperties(schemaObject) > policy.maxTotalProperties
  ) {
    return { value: null, error: `JSON Schema 전체 property는 ${policy.maxTotalProperties}개 이하여야 합니다.` };
  }
  if (policy.requireRootObject && schemaObject.type !== 'object') {
    return { value: null, error: 'JSON Schema root type은 object여야 합니다.' };
  }
  if (policy.requireAdditionalPropertiesFalse) {
    const missing = schemaObjects(schemaObject).some((item) => (
      (item.type === 'object' || (typeof item.properties === 'object' && item.properties !== null))
      && item.additionalProperties !== false
    ));
    if (missing) {
      return { value: null, error: '모든 object schema는 additionalProperties:false가 필요합니다.' };
    }
  }

  const jsonSchema: Record<string, unknown> = { name, schema: schemaObject };
  if (policy.strictRequireTrue) {
    jsonSchema.strict = true;
  } else if (policy.strictAllowed && settings.jsonSchemaStrict !== null) {
    jsonSchema.strict = settings.jsonSchemaStrict;
  }
  return {
    value: { type: 'json_schema', json_schema: jsonSchema },
    error: null,
  };
}

// 대화 기록은 성공한 주고받기만 보낸다. 실패하거나 빈 답을 보내면 user 메시지가
// 연속되고, 역할이 번갈아야 하는 chat template은 그 요청을 거부한다.
function assistantHistoryMessage(turn: AssistantTurn): ChatMessage {
  return {
    role: 'assistant',
    content: turn.content || null,
    ...(turn.toolCalls.length > 0 ? { tool_calls: turn.toolCalls.map((call) => ({
      id: call.id,
      type: 'function' as const,
      function: { ...call.function },
    })) } : {}),
  };
}

function historyMessages(exchanges: readonly Exchange[], systemPrompt: string): ChatMessage[] {
  const messages: ChatMessage[] = [];
  if (systemPrompt.trim()) messages.push({ role: 'system', content: systemPrompt });
  for (const exchange of exchanges) {
    if (!exchangeIncludedInHistory(exchange)) continue;
    const toolResults = exchange.toolResults ?? [];
    if (toolResults.length > 0) {
      messages.push(...toolResults.map((result): ChatMessage => ({
        role: 'tool',
        content: result.content,
        tool_call_id: result.toolCallId,
      })));
    } else {
      messages.push({
        role: 'user',
        content: userMessageContent(exchange.user, exchange.attachments),
      });
    }
    messages.push(assistantHistoryMessage(exchange.assistant));
  }
  return messages;
}

export function conversationMessages(
  exchanges: readonly Exchange[],
  nextUserText: string,
  systemPrompt: string,
  nextAttachments: readonly ChatAttachment[] = [],
): ChatMessage[] {
  return [
    ...historyMessages(exchanges, systemPrompt),
    { role: 'user', content: userMessageContent(nextUserText, nextAttachments) },
  ];
}

function buildRequestFromMessages(
  model: PublicModel,
  settings: ChatSettings,
  messages: ChatMessage[],
): { body: Record<string, unknown>; error: string | null } {
  const controls = chatControls(model);
  const body: Record<string, unknown> = { model: model.id, messages };

  const streamEnabled = controls.stream
    ? controls.stream.constValue ?? settings.stream
    : false;
  if (controls.stream) {
    body.stream = streamEnabled;
    if (streamEnabled && controls.includeUsage) body.stream_options = { include_usage: true };
  }

  const numericSettings: Array<{
    control: NumberControl | null;
    raw: string;
    label: string;
    requestName: string;
  }> = [
    { control: controls.temperature, raw: settings.temperature, label: '온도', requestName: 'temperature' },
    { control: controls.maxTokens, raw: settings.maxTokens, label: '최대 출력 토큰', requestName: 'max_tokens' },
    { control: controls.topP, raw: settings.topP, label: 'Top P', requestName: 'top_p' },
    { control: controls.topK, raw: settings.topK, label: 'Top K', requestName: 'top_k' },
    { control: controls.minP, raw: settings.minP, label: 'Min P', requestName: 'min_p' },
    { control: controls.presencePenalty, raw: settings.presencePenalty, label: '존재 페널티', requestName: 'presence_penalty' },
    { control: controls.frequencyPenalty, raw: settings.frequencyPenalty, label: '빈도 페널티', requestName: 'frequency_penalty' },
    { control: controls.repetitionPenalty, raw: settings.repetitionPenalty, label: '반복 페널티', requestName: 'repetition_penalty' },
    { control: controls.seed, raw: settings.seed, label: 'Seed', requestName: 'seed' },
  ];
  for (const item of numericSettings) {
    if (!item.control) continue;
    const parsed = parseControlValue(item.raw, item.control, item.label);
    if (parsed.error) return { body, error: parsed.error };
    if (parsed.value !== null) body[item.requestName] = parsed.value;
  }

  if (controls.stop) {
    const parsed = parseStopValue(settings.stop, controls.stop);
    if (parsed.error) return { body, error: parsed.error };
    if (parsed.value !== null) body.stop = parsed.value;
  }

  if (controls.reasoning && settings.reasoning !== null) {
    if (controls.reasoning.constValue !== null && settings.reasoning !== controls.reasoning.constValue) {
      return { body, error: `추론 출력은 현재 모델 정책에서 ${controls.reasoning.constValue ? '켜짐' : '꺼짐'}으로 고정되어 있습니다.` };
    }
    body.reasoning = settings.reasoning;
  }

  const logprobsEnabled = controls.logprobs
    ? controls.logprobs.constValue ?? settings.logprobs
    : null;
  if (controls.logprobs && settings.logprobs !== null) {
    if (controls.logprobs.constValue !== null && settings.logprobs !== controls.logprobs.constValue) {
      return { body, error: `로그확률은 현재 모델 정책에서 ${controls.logprobs.constValue ? '켜짐' : '꺼짐'}으로 고정되어 있습니다.` };
    }
    if (settings.logprobs && streamEnabled && controls.logprobs.allowStream === false) {
      return { body, error: '현재 모델은 스트리밍 응답에서 로그확률을 지원하지 않습니다.' };
    }
    body.logprobs = settings.logprobs;
  }

  if (controls.topLogprobs) {
    const parsed = parseControlValue(settings.topLogprobs, controls.topLogprobs, 'Top logprobs');
    if (parsed.error) return { body, error: parsed.error };
    if (parsed.value !== null) {
      if (controls.topLogprobs.requires.logprobs === true && logprobsEnabled !== true) {
        return { body, error: 'Top logprobs를 사용하려면 로그확률을 켜야 합니다.' };
      }
      body.top_logprobs = parsed.value;
    }
  }

  const toolParams = toolRequestParameters(controls.tools, settings);
  if (toolParams.error) return { body, error: toolParams.error };
  Object.assign(body, toolParams.value);

  if (controls.responseFormat) {
    const structured = structuredResponseFormat(controls.responseFormat, settings, messages);
    if (structured.error) return { body, error: structured.error };
    if (structured.value) body.response_format = structured.value;
  }
  return { body, error: null };
}

export function buildChatRequest(
  model: PublicModel,
  settings: ChatSettings,
  exchanges: readonly Exchange[],
  nextUserText: string,
  nextAttachments: readonly ChatAttachment[] = [],
): { body: Record<string, unknown>; error: string | null } {
  if (!nextUserText && nextAttachments.length === 0) {
    return { body: {}, error: '메시지나 첨부 파일을 입력하세요.' };
  }
  if (pendingToolCallExchange(exchanges) !== null) {
    return { body: {}, error: '먼저 대기 중인 tool call의 결과를 입력해 대화를 이어가세요.' };
  }
  const attachmentError = validateChatAttachments(
    model,
    [...conversationAttachments(exchanges), ...nextAttachments],
  );
  if (attachmentError) return { body: {}, error: attachmentError };
  return buildRequestFromMessages(
    model,
    settings,
    conversationMessages(exchanges, nextUserText, settings.systemPrompt, nextAttachments),
  );
}

export function buildToolResultRequest(
  model: PublicModel,
  settings: ChatSettings,
  exchanges: readonly Exchange[],
  sourceExchangeId: number,
  results: readonly ChatToolResult[],
): { body: Record<string, unknown>; error: string | null } {
  const source = exchanges.find((exchange) => exchange.id === sourceExchangeId);
  if (!source || source.assistant.status !== 'complete' || source.assistant.finishReason !== 'tool_calls') {
    return { body: {}, error: '완료된 tool call에만 결과를 연결할 수 있습니다.' };
  }
  const calls = source.assistant.toolCalls;
  if (calls.length === 0) return { body: {}, error: '연결할 tool call이 없습니다.' };
  if (results.length !== calls.length) {
    return { body: {}, error: '모든 tool call의 결과를 함께 입력해야 합니다.' };
  }
  const callIds = new Set(calls.map((call) => call.id));
  const resultIds = new Set(results.map((result) => result.toolCallId));
  if (resultIds.size !== results.length || resultIds.size !== callIds.size || [...resultIds].some((id) => !callIds.has(id))) {
    return { body: {}, error: 'Tool result의 tool_call_id가 assistant tool call과 일치해야 합니다.' };
  }
  const alreadyResolved = exchanges.some((exchange) => toolResultsResolveSource(source, exchange));
  if (alreadyResolved) return { body: {}, error: '이미 결과를 보낸 tool call입니다.' };
  if (chatControls(model).tools === null) {
    return { body: {}, error: '현재 모델은 도구 호출을 광고하지 않아 이 대화를 이어갈 수 없습니다.' };
  }
  const attachmentError = validateChatAttachments(model, conversationAttachments(exchanges));
  if (attachmentError) return { body: {}, error: attachmentError };

  const messages = historyMessages(exchanges, settings.systemPrompt);
  messages.push(...results.map((result): ChatMessage => ({
    role: 'tool',
    content: result.content,
    tool_call_id: result.toolCallId,
  })));
  return buildRequestFromMessages(model, settings, messages);
}

export function startTurn(now: number): AssistantTurn {
  return {
    status: 'streaming',
    content: '',
    reasoning: '',
    toolCalls: [],
    finishReason: null,
    usage: null,
    error: null,
    requestId: null,
    startedAt: now,
    firstTokenAt: null,
    finishedAt: null,
  };
}

function applyToolCallDeltas(
  current: readonly ChatToolCall[],
  deltas: readonly ChatToolCallDelta[],
): ChatToolCall[] {
  const next = current.map((call) => ({
    ...call,
    function: { ...call.function },
  }));
  for (const delta of deltas) {
    while (next.length <= delta.index) {
      next.push({ id: '', type: 'function', function: { name: '', arguments: '' } });
    }
    const call = next[delta.index];
    if (delta.id) call.id = delta.id;
    if (delta.type === 'function') call.type = 'function';
    call.function.name += delta.name;
    call.function.arguments += delta.arguments;
  }
  return next;
}

export function applyChatUpdate(turn: AssistantTurn, update: ChatStreamUpdate, now: number): AssistantTurn {
  if (turn.status !== 'streaming') return turn;
  switch (update.kind) {
    case 'chunk': {
      const toolCallDeltas = update.toolCallDeltas ?? [];
      const produced = update.content !== '' || update.reasoning !== '' || toolCallDeltas.length > 0;
      return {
        ...turn,
        content: turn.content + update.content,
        reasoning: turn.reasoning + update.reasoning,
        toolCalls: applyToolCallDeltas(turn.toolCalls, toolCallDeltas),
        finishReason: update.finishReason ?? turn.finishReason,
        usage: update.usage ?? turn.usage,
        firstTokenAt: turn.firstTokenAt ?? (produced ? now : null),
      };
    }
    case 'error':
      return {
        ...turn,
        status: 'failed',
        error: { code: update.code, message: update.message },
        requestId: turn.requestId ?? update.requestId,
        finishedAt: now,
      };
    case 'done':
      return { ...turn, status: 'complete', finishedAt: now };
    default:
      return turn;
  }
}

// [DONE] 없이 연결이 끝나도 받은 내용은 완료로 본다. 중단·실패는 이미 상태가 바뀌어 있다.
export function finishTurn(turn: AssistantTurn, now: number): AssistantTurn {
  return turn.status === 'streaming' ? { ...turn, status: 'complete', finishedAt: now } : turn;
}

export function stopTurn(turn: AssistantTurn, now: number): AssistantTurn {
  return turn.status === 'streaming' ? { ...turn, status: 'stopped', finishedAt: now } : turn;
}

export function failTurn(
  turn: AssistantTurn,
  error: { code: string | null; message: string; requestId?: string | null },
  now: number,
): AssistantTurn {
  if (turn.status !== 'streaming') return turn;
  return {
    ...turn,
    status: 'failed',
    error: { code: error.code, message: error.message },
    requestId: turn.requestId ?? error.requestId ?? null,
    finishedAt: now,
  };
}

function toolCallsFromResponse(value: unknown): ChatToolCall[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const call = objectOrEmpty(item);
    const fn = objectOrEmpty(call.function);
    if (
      call.type !== 'function'
      || typeof call.id !== 'string'
      || typeof fn.name !== 'string'
      || typeof fn.arguments !== 'string'
    ) return [];
    return [{
      id: call.id,
      type: 'function' as const,
      function: { name: fn.name, arguments: fn.arguments },
    }];
  });
}

// 비스트리밍 응답(stream을 광고하지 않는 모델)을 같은 turn 모양으로 옮긴다.
export function completeFromResponse(turn: AssistantTurn, payload: unknown, now: number): AssistantTurn {
  const body = typeof payload === 'object' && payload !== null ? (payload as Record<string, unknown>) : {};
  const choice = Array.isArray(body.choices) ? (body.choices[0] as Record<string, unknown> | undefined) : undefined;
  const message = (choice?.message ?? {}) as Record<string, unknown>;
  const usage = body.usage as ChatUsage | undefined;
  return {
    ...turn,
    status: 'complete',
    content: typeof message.content === 'string' ? message.content : '',
    reasoning: typeof message.reasoning === 'string'
      ? message.reasoning
      : typeof message.reasoning_content === 'string' ? message.reasoning_content : '',
    toolCalls: toolCallsFromResponse(message.tool_calls),
    finishReason: typeof choice?.finish_reason === 'string' ? choice.finish_reason : null,
    usage: usage && typeof usage.completion_tokens === 'number' ? usage : null,
    // 한 번에 받은 응답에는 첫 토큰 시점이 없다. 전체 시간과 같은 값을 첫 토큰으로 보이지 않는다.
    firstTokenAt: null,
    finishedAt: now,
  };
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}초`;
}

export type TurnFact = { label: string; value: string };

export function turnFacts(turn: AssistantTurn): TurnFact[] {
  const facts: TurnFact[] = [];
  if (turn.firstTokenAt !== null) {
    facts.push({ label: '첫 토큰', value: formatDuration(turn.firstTokenAt - turn.startedAt) });
  }
  if (turn.finishedAt !== null) {
    facts.push({ label: '전체', value: formatDuration(turn.finishedAt - turn.startedAt) });
  }
  if (turn.usage) {
    facts.push({
      label: '토큰',
      value: `입력 ${turn.usage.prompt_tokens.toLocaleString('ko-KR')} · 출력 ${turn.usage.completion_tokens.toLocaleString('ko-KR')}`,
    });
    const generationMs = turn.finishedAt !== null && turn.firstTokenAt !== null
      ? turn.finishedAt - turn.firstTokenAt
      : 0;
    // 첫 토큰 이후 구간만 생성 속도로 본다. 너무 짧으면 비율이 의미 없는 값이 된다.
    if (turn.usage.completion_tokens > 1 && generationMs >= 200) {
      facts.push({
        label: '생성 속도',
        value: `${((turn.usage.completion_tokens - 1) / (generationMs / 1000)).toFixed(1)} tok/s`,
      });
    }
  }
  return facts;
}

export function turnNotice(turn: AssistantTurn): string | null {
  if (turn.status === 'stopped') return '중지했습니다. 받은 부분까지만 표시합니다.';
  if (turn.status === 'failed') return null;
  if (turn.finishReason === 'length') return '최대 출력 토큰에 도달해 응답이 잘렸습니다.';
  if (turn.status === 'complete' && !turn.content && turn.toolCalls.length === 0 && turn.reasoning) {
    return '생각 과정만 생성되고 답변은 없습니다. 최대 출력 토큰을 늘려 보세요.';
  }
  return null;
}
