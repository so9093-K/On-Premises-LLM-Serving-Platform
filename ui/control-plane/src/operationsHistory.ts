/** 복수 커서 페이지에 겹치는 작업이 있어도 가장 최근 상태만 표시한다. */
export function mergeOperationPages<T extends { operation_id: string; updated_at: number }>(
  pages: readonly (readonly T[])[],
): T[] {
  const latest = new Map<string, T>();
  for (const page of pages) {
    for (const item of page) {
      const previous = latest.get(item.operation_id);
      // 최신 페이지를 먼저 탐색하므로 동일한 시간에는 먼저 나온 항목을 우선한다.
      if (previous === undefined || item.updated_at > previous.updated_at) {
        latest.set(item.operation_id, item);
      }
    }
  }
  return Array.from(latest.values());
}
