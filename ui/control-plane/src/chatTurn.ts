import type { AssistantTurn, ChatToolCall } from './chatSession.ts';
import type { ChatStreamUpdate, ChatToolCallDelta } from './chatStream.ts';

// 응답 수명주기의 순수 상태 전환. UI와 네트워크 경계를 참조하지 않는다.

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

// 종료 신호 없이 닫힌 stream은 readChatStream이 실패로 표시한다. 그 상태를 유지한다.
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

function formatDuration(ms: number): string {
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
  if (turn.status === 'failed') {
    // Static Target에서는 공개 모델 목록이 정상이어도 모델 Runtime이 내려가 있을 수 있다.
    // 오류 코드만으로는 다음 행동을 알 수 없으므로 복구 경로를 안내한다.
    return turn.error?.code === 'MODEL_UNAVAILABLE'
      ? '모델 Runtime이 요청을 받을 수 없는 상태입니다. Request ID를 서버 운영자에게 전달하거나, 서버에서 make status로 Runtime 상태를 확인한 뒤 다시 보내세요.'
      : null;
  }
  if (turn.finishReason === 'length') return '최대 출력 토큰에 도달해 응답이 잘렸습니다.';
  if (turn.status === 'complete' && !turn.content && turn.toolCalls.length === 0 && turn.reasoning) {
    return '생각 과정만 생성되고 답변은 없습니다. 최대 출력 토큰을 늘려 보세요.';
  }
  return null;
}
