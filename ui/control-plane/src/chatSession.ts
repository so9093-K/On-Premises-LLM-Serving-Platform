// 채팅 테스트 화면의 순수 로직. 요청 본문은 /v1/models가 광고한 request_parameters
// 안에서만 만들고, 응답 누적과 지연 측정은 화면과 분리해 테스트한다.
import type { ChatStreamUpdate, ChatUsage } from './chatStream';

type ParameterSpec = Record<string, unknown>;

export type PublicModel = {
  id: string;
  capabilities: readonly string[];
  request_parameters: Record<string, ParameterSpec>;
};

export type NumberControl = { min: number; max: number | null; integer: boolean };

export type ChatControls = {
  temperature: NumberControl | null;
  maxTokens: NumberControl | null;
  reasoning: { defaultEnabled: boolean } | null;
  stream: boolean;
  includeUsage: boolean;
};

export type ChatSettings = {
  systemPrompt: string;
  temperature: string;
  maxTokens: string;
  reasoning: boolean | null;
};

export type TurnStatus = 'streaming' | 'complete' | 'stopped' | 'failed';

export type AssistantTurn = {
  status: TurnStatus;
  content: string;
  reasoning: string;
  finishReason: string | null;
  usage: ChatUsage | null;
  error: { code: string | null; message: string } | null;
  requestId: string | null;
  startedAt: number;
  firstTokenAt: number | null;
  finishedAt: number | null;
};

export type Exchange = {
  id: number;
  user: string;
  sentAtSeconds: number;
  assistant: AssistantTurn;
};

export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string };

export function chatCapableModels(models: readonly PublicModel[]): PublicModel[] {
  return models.filter((model) => model.capabilities.includes('chat.completions'));
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function numberControl(spec: ParameterSpec | undefined, integer: boolean): NumberControl | null {
  if (spec === undefined) return null;
  const min = finite(spec.min) ?? finite(spec.min_exclusive) ?? 0;
  return { min, max: finite(spec.max), integer };
}

export function chatControls(model: PublicModel): ChatControls {
  const params = model.request_parameters;
  const reasoning = params.reasoning;
  return {
    temperature: numberControl(params.temperature, false),
    maxTokens: numberControl(params.max_tokens, true),
    reasoning: reasoning === undefined ? null : { defaultEnabled: reasoning.default === true },
    stream: params.stream !== undefined,
    includeUsage: params.stream_options !== undefined,
  };
}

// 빈 값과 null은 "모델 기본값"이다. 요청에서 빼면 활성 profile이 기본값을 정한다.
export const DEFAULT_CHAT_SETTINGS: ChatSettings = {
  systemPrompt: '',
  temperature: '',
  maxTokens: '',
  reasoning: null,
};

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
  if (value < control.min || (control.max !== null && value > control.max)) {
    const range = control.max === null ? `${control.min} 이상` : `${control.min}–${control.max}`;
    return { value: null, error: `${label}은(는) ${range} 범위여야 합니다.` };
  }
  return { value, error: null };
}

// 대화 기록은 성공한 주고받기만 보낸다. 실패하거나 빈 답을 보내면 user 메시지가
// 연속되고, 역할이 번갈아야 하는 chat template은 그 요청을 거부한다.
export function conversationMessages(
  exchanges: readonly Exchange[],
  nextUserText: string,
  systemPrompt: string,
): ChatMessage[] {
  const messages: ChatMessage[] = [];
  if (systemPrompt.trim()) messages.push({ role: 'system', content: systemPrompt });
  for (const exchange of exchanges) {
    if (exchange.assistant.status === 'failed' || !exchange.assistant.content) continue;
    messages.push({ role: 'user', content: exchange.user });
    messages.push({ role: 'assistant', content: exchange.assistant.content });
  }
  messages.push({ role: 'user', content: nextUserText });
  return messages;
}

export function buildChatRequest(
  model: PublicModel,
  settings: ChatSettings,
  exchanges: readonly Exchange[],
  nextUserText: string,
): { body: Record<string, unknown>; error: string | null } {
  const controls = chatControls(model);
  const body: Record<string, unknown> = {
    model: model.id,
    messages: conversationMessages(exchanges, nextUserText, settings.systemPrompt),
  };
  if (controls.stream) {
    body.stream = true;
    if (controls.includeUsage) body.stream_options = { include_usage: true };
  }
  if (controls.temperature) {
    const parsed = parseControlValue(settings.temperature, controls.temperature, '온도');
    if (parsed.error) return { body, error: parsed.error };
    if (parsed.value !== null) body.temperature = parsed.value;
  }
  if (controls.maxTokens) {
    const parsed = parseControlValue(settings.maxTokens, controls.maxTokens, '최대 출력 토큰');
    if (parsed.error) return { body, error: parsed.error };
    if (parsed.value !== null) body.max_tokens = parsed.value;
  }
  if (controls.reasoning && settings.reasoning !== null) body.reasoning = settings.reasoning;
  return { body, error: null };
}

export function startTurn(now: number): AssistantTurn {
  return {
    status: 'streaming',
    content: '',
    reasoning: '',
    finishReason: null,
    usage: null,
    error: null,
    requestId: null,
    startedAt: now,
    firstTokenAt: null,
    finishedAt: null,
  };
}

export function applyChatUpdate(turn: AssistantTurn, update: ChatStreamUpdate, now: number): AssistantTurn {
  if (turn.status !== 'streaming') return turn;
  switch (update.kind) {
    case 'chunk': {
      const produced = update.content !== '' || update.reasoning !== '';
      return {
        ...turn,
        content: turn.content + update.content,
        reasoning: turn.reasoning + update.reasoning,
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
  if (turn.status === 'complete' && !turn.content && turn.reasoning) {
    return '생각 과정만 생성되고 답변은 없습니다. 최대 출력 토큰을 늘려 보세요.';
  }
  return null;
}
