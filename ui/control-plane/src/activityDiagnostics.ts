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

export function mainRuntimeDiagnosticsUrl(
  grafanaBaseUrl: string | null,
  updatedAtSeconds: number,
): string | null {
  return dashboardUrl(grafanaBaseUrl, 'main-runtime-health', updatedAtSeconds);
}
