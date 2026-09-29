// API timestamp는 epoch seconds다. 값 하나가 잘못되어도 화면 전체가 멈추지 않도록
// Date 변환 실패는 표시값 '—'과 생략된 dateTime으로 접는다.

function epochDate(seconds: unknown): Date | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return null;
  const date = new Date(seconds * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTimestamp(seconds: unknown): string {
  return epochDate(seconds)?.toLocaleString('ko-KR') ?? '—';
}

export function isoTimestamp(seconds: unknown): string | undefined {
  return epochDate(seconds)?.toISOString();
}
