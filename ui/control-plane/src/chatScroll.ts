// Presentation-only follow policy. Request and streaming authority remains in Gateway.
const CHAT_FOLLOW_DISTANCE_PX = 160;

export function conversationEndNearViewport(endTop: number, viewportHeight: number): boolean {
  return Number.isFinite(endTop) && Number.isFinite(viewportHeight)
    && Math.abs(endTop - viewportHeight) < CHAT_FOLLOW_DISTANCE_PX;
}
