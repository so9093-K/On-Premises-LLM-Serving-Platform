import type { ChatAttachment, Exchange } from './chatSession';

export function exchangeIncludedInHistory(exchange: Exchange): boolean {
  const turn = exchange.assistant;
  if (turn.status === 'failed') return false;
  if (turn.toolCalls.length > 0) {
    return turn.status === 'complete'
      && turn.finishReason === 'tool_calls'
      && turn.toolCalls.every((call) => call.id !== '' && call.function.name !== '');
  }
  return turn.content !== '';
}

export function toolResultsResolveSource(source: Exchange, candidate: Exchange): boolean {
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

