// Gateway의 Chat Completions SSE를 읽는다. 외부 SDK 없이 WHATWG EventSource와 같은
// 규칙으로 줄을 나누고, 네트워크 조각이 줄·글자 경계를 가르더라도 결과가 같아야 한다.

export type SseEvent = {
  event: string;
  data: string;
};

export type SseParser = {
  push: (text: string) => SseEvent[];
  finish: () => SseEvent[];
};

export function createSseParser(): SseParser {
  let buffer = '';
  let eventName = '';
  let dataLines: string[] = [];

  function dispatch(events: SseEvent[]): void {
    if (dataLines.length > 0) {
      events.push({ event: eventName || 'message', data: dataLines.join('\n') });
    }
    eventName = '';
    dataLines = [];
  }

  function processLine(line: string, events: SseEvent[]): void {
    if (line === '') {
      dispatch(events);
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') dataLines.push(value);
    else if (field === 'event') eventName = value;
  }

  function drain(final: boolean): SseEvent[] {
    const events: SseEvent[] = [];
    const terminator = /\r\n|\r|\n/g;
    let start = 0;
    let match: RegExpExecArray | null;
    while ((match = terminator.exec(buffer)) !== null) {
      // 조각 끝의 \r 뒤에 \n이 올 수 있다. 다음 조각을 볼 때까지 줄을 끝내지 않는다.
      if (!final && match[0] === '\r' && match.index === buffer.length - 1) break;
      processLine(buffer.slice(start, match.index), events);
      start = match.index + match[0].length;
    }
    buffer = buffer.slice(start);
    if (final) {
      if (buffer !== '') processLine(buffer, events);
      buffer = '';
      // 마지막 빈 줄 없이 끊긴 event도 버리지 않는다. 운영자가 보는 화면이므로
      // 받은 글자를 잃는 쪽보다 보여 주는 쪽이 낫다.
      dispatch(events);
    }
    return events;
  }

  return {
    push(text: string) {
      buffer += text;
      return drain(false);
    },
    finish() {
      return drain(true);
    },
  };
}

export type ChatUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
};

export type ChatToolCallDelta = {
  index: number;
  id: string;
  type: string;
  name: string;
  arguments: string;
};

export type ChatStreamUpdate =
  | {
      kind: 'chunk';
      content: string;
      reasoning: string;
      toolCallDeltas: ChatToolCallDelta[];
      finishReason: string | null;
      usage: ChatUsage | null;
    }
  | { kind: 'error'; code: string | null; message: string; requestId: string | null }
  | { kind: 'done' }
  | { kind: 'ignored' };

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function toolCallDeltasFrom(value: unknown): ChatToolCallDelta[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const call = record(item);
    const fn = record(call?.function);
    const index = call?.index;
    if (typeof index !== 'number' || !Number.isInteger(index) || index < 0) return [];
    return [{
      index,
      id: text(call?.id),
      type: text(call?.type),
      name: text(fn?.name),
      arguments: text(fn?.arguments),
    }];
  });
}

function usageFrom(value: unknown): ChatUsage | null {
  const usage = record(value);
  if (usage === null) return null;
  const numbers = ['prompt_tokens', 'completion_tokens', 'total_tokens'].map((key) => usage[key]);
  if (!numbers.every((item) => typeof item === 'number' && Number.isFinite(item))) return null;
  const [prompt, completion, total] = numbers as number[];
  return { prompt_tokens: prompt, completion_tokens: completion, total_tokens: total };
}

export function errorFromPayload(payload: unknown, fallback: string): {
  code: string | null;
  message: string;
  requestId: string | null;
} {
  const error = record(record(payload)?.error);
  return {
    code: typeof error?.code === 'string' && error.code ? error.code : null,
    message: typeof error?.message === 'string' && error.message ? error.message : fallback,
    requestId: typeof error?.request_id === 'string' && error.request_id ? error.request_id : null,
  };
}

export function interpretChatEvent(event: SseEvent): ChatStreamUpdate {
  if (event.data === '[DONE]') return { kind: 'done' };
  let payload: unknown;
  try {
    payload = JSON.parse(event.data);
  } catch {
    return event.event === 'error'
      ? { kind: 'error', code: null, message: event.data || '스트림 오류', requestId: null }
      : { kind: 'ignored' };
  }
  if (event.event === 'error' || record(payload)?.error !== undefined) {
    return { kind: 'error', ...errorFromPayload(payload, '스트리밍 중 오류가 발생했습니다.') };
  }
  const chunk = record(payload);
  if (chunk === null) return { kind: 'ignored' };
  // 플레이그라운드는 n=1만 보낸다. 첫 choice만 읽는다.
  const choices = Array.isArray(chunk.choices) ? chunk.choices : [];
  const choice = record(choices[0]);
  const delta = record(choice?.delta);
  const finishReason = choice?.finish_reason;
  return {
    kind: 'chunk',
    content: text(delta?.content),
    // vLLM reasoning parser는 버전에 따라 reasoning 또는 reasoning_content를 쓴다.
    reasoning: text(delta?.reasoning) || text(delta?.reasoning_content),
    toolCallDeltas: toolCallDeltasFrom(delta?.tool_calls),
    finishReason: typeof finishReason === 'string' && finishReason ? finishReason : null,
    usage: usageFrom(chunk.usage),
  };
}

export async function readChatStream(
  body: ReadableStream<Uint8Array>,
  onUpdate: (update: ChatStreamUpdate) => void,
): Promise<void> {
  const reader = body.getReader();
  // stream 옵션이 여러 byte 글자가 조각 경계에 걸려도 다음 조각까지 들고 있는다.
  const decoder = new TextDecoder('utf-8');
  const parser = createSseParser();
  const emit = (events: SseEvent[]) => {
    for (const event of events) onUpdate(interpretChatEvent(event));
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      emit(parser.push(decoder.decode(value, { stream: true })));
    }
    emit(parser.push(decoder.decode()));
    emit(parser.finish());
  } finally {
    reader.releaseLock();
  }
}
