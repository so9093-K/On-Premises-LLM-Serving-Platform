// Presentation-only follow policy. Request and streaming authority remains in Gateway.
const CHAT_FOLLOW_DISTANCE_PX = 160;
// 응답이 끝나면 지표·request_id·내보내기가 답변 아래에 붙는다. 끝까지 따라가면 짧은 답변이
// 화면 밖으로 밀리므로, 부가 정보는 시작 부분만 보이는 위치까지 따라간다.
const CHAT_DETAILS_PEEK_PX = 56;

export function conversationEndNearViewport(endTop: number, viewportHeight: number): boolean {
  return Number.isFinite(endTop) && Number.isFinite(viewportHeight)
    && Math.abs(endTop - viewportHeight) < CHAT_FOLLOW_DISTANCE_PX;
}

export function followScrollTop(detailsTop: number | null, scrollHeight: number, viewportHeight: number): number {
  const end = Math.max(0, scrollHeight - viewportHeight);
  if (detailsTop === null || !Number.isFinite(detailsTop)) return end;
  return Math.min(end, Math.max(0, detailsTop + CHAT_DETAILS_PEEK_PX - viewportHeight));
}
