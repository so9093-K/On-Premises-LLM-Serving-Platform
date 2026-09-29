const DIAGNOSTIC_WINDOW_MS = 15 * 60 * 1000;

function regexLiteral(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function dashboardUrl(
  grafanaBaseUrl: string | null,
  dashboardUid: string,
  updatedAtSeconds: number,
  variables: Record<string, string> = {},
): string | null {
  if (!grafanaBaseUrl) return null;

  try {
    const base = new URL(grafanaBaseUrl.endsWith('/') ? grafanaBaseUrl : `${grafanaBaseUrl}/`);
    if (base.protocol !== 'http:' && base.protocol !== 'https:') return null;

    const url = new URL(`d/${dashboardUid}`, base);
    const center = Math.round(updatedAtSeconds * 1000);
    url.searchParams.set('from', String(Math.max(0, center - DIAGNOSTIC_WINDOW_MS)));
    url.searchParams.set('to', String(center + DIAGNOSTIC_WINDOW_MS));

    for (const [name, value] of Object.entries(variables)) {
      url.searchParams.set(`var-${name}`, value);
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function requestLogDiagnosticsUrl(
  grafanaBaseUrl: string | null,
  requestId: string,
  updatedAtSeconds: number,
): string | null {
  const normalized = requestId.trim();
  if (!normalized) return null;
  return dashboardUrl(
    grafanaBaseUrl,
    'request_log_explorer',
    updatedAtSeconds,
    {
      service: 'gateway',
      request_id_filter: `^${regexLiteral(normalized)}$`,
    },
  );
}

// 메인 런타임 지표는 target마다 다른 Dashboard가 소유한다. MLX runtime 전용 Dashboard는
// Apple Silicon target에만 provisioning되고, vLLM target은 서비스 개요가 메인 모델 지표를 보여 준다.
export function mainRuntimeDashboardUid(runtimeBackend: string): string {
  return runtimeBackend === 'mlx-vlm' ? 'main-runtime-health' : 'service_overview';
}

export function mainRuntimeDiagnosticsUrl(
  grafanaBaseUrl: string | null,
  runtimeBackend: string,
  updatedAtSeconds: number,
): string | null {
  return dashboardUrl(grafanaBaseUrl, mainRuntimeDashboardUid(runtimeBackend), updatedAtSeconds);
}
