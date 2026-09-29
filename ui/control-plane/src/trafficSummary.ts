// Gateway가 집계한 최근 공개 API 트래픽을 운영자가 읽는 문장으로 바꾼다. 판정 색은
// 근거가 있는 경우(5xx 발생)에만 쓰고, 지연은 SLO가 소유하므로 색으로 판정하지 않는다.

type Distribution = {
  samples: number;
  p50: number | null;
  p95: number | null;
};

export type RecentTrafficSummary = {
  window_seconds: number;
  observed_seconds: number;
  minimum_samples: { p50: number; p95: number };
  requests: { total: number; client_errors: number; server_errors: number };
  completion_latency_seconds: Distribution;
  time_to_first_chunk_seconds: Distribution;
};

export type TrafficTone = 'neutral' | 'good' | 'warning';

export type TrafficTile = {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: TrafficTone;
};

export function formatSeconds(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(1)}초`;
}

function formatMinutes(seconds: number): string {
  const minutes = seconds / 60;
  return Number.isInteger(minutes) ? `${minutes}분` : `${minutes.toFixed(1)}분`;
}

export function trafficWindowLabel(summary: RecentTrafficSummary): string {
  const window = `최근 ${formatMinutes(summary.window_seconds)}`;
  if (summary.observed_seconds + 1 < summary.window_seconds) {
    return `${window} (Gateway 시작 후 ${formatMinutes(Math.max(60, Math.round(summary.observed_seconds / 60) * 60))} 관측)`;
  }
  return window;
}

function latencyTile(
  key: string,
  label: string,
  distribution: Distribution,
  minimumP95: number,
): TrafficTile {
  if (distribution.p95 === null) {
    return {
      key,
      label,
      value: distribution.samples === 0 ? '요청 없음' : '표본 부족',
      detail: distribution.samples === 0
        ? '이 구간에 해당 요청이 없습니다.'
        : `p95는 ${minimumP95}건 이상일 때 계산합니다 (현재 ${distribution.samples}건).`,
      tone: 'neutral',
    };
  }
  return {
    key,
    label,
    value: formatSeconds(distribution.p95),
    detail: `p50 ${formatSeconds(distribution.p50)} · 표본 ${distribution.samples}건`,
    tone: 'neutral',
  };
}

export function trafficTiles(summary: RecentTrafficSummary): TrafficTile[] {
  const { total, client_errors: clientErrors, server_errors: serverErrors } = summary.requests;
  const minutes = Math.max(summary.observed_seconds, 1) / 60;
  const serverRate = total > 0 ? (serverErrors / total) * 100 : 0;
  return [
    {
      key: 'requests',
      label: '요청',
      value: `${total.toLocaleString('ko-KR')}건`,
      detail: total > 0 ? `분당 ${(total / minutes).toFixed(1)}건` : '이 구간에 공개 API 요청이 없습니다.',
      tone: 'neutral',
    },
    {
      key: 'server-errors',
      label: '서버 오류',
      value: `${serverErrors.toLocaleString('ko-KR')}건`,
      detail: total > 0
        ? `${serverRate.toFixed(serverRate > 0 && serverRate < 1 ? 2 : 1)}% · 요청 거부(4xx) ${clientErrors.toLocaleString('ko-KR')}건`
        : `요청 거부(4xx) ${clientErrors.toLocaleString('ko-KR')}건`,
      tone: serverErrors > 0 ? 'warning' : 'good',
    },
    latencyTile('completion-latency', '응답 시간 p95', summary.completion_latency_seconds, summary.minimum_samples.p95),
    latencyTile('first-chunk', '첫 응답 p95 (스트리밍)', summary.time_to_first_chunk_seconds, summary.minimum_samples.p95),
  ];
}
