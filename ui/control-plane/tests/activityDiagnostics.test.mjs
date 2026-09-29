import assert from 'node:assert/strict';
import test from 'node:test';

import {
  mainRuntimeDiagnosticsUrl,
  requestLogDiagnosticsUrl,
} from '../src/activityDiagnostics.ts';

test('request log diagnostics deep-link exact request id into the existing Grafana dashboard', () => {
  const href = requestLogDiagnosticsUrl(
    'http://127.0.0.1:9411',
    'req_abc.123',
    1_700_000_000,
  );
  assert.notEqual(href, null);

  const url = new URL(href);
  assert.equal(url.pathname, '/d/request_log_explorer');
  assert.equal(url.searchParams.get('var-service'), 'gateway');
  assert.equal(url.searchParams.get('var-request_id_filter'), '^req_abc\\.123$');
  assert.equal(url.searchParams.get('from'), '1699999100000');
  assert.equal(url.searchParams.get('to'), '1700000900000');
});

test('diagnostic links preserve an explicit Grafana path prefix', () => {
  const href = mainRuntimeDiagnosticsUrl(
    'https://ops.example.test/grafana',
    'mlx-vlm',
    1_700_000_000,
  );
  assert.notEqual(href, null);

  const url = new URL(href);
  assert.equal(url.pathname, '/grafana/d/main-runtime-health');
});

test('main runtime diagnostics open a dashboard the target actually provisions', () => {
  // MLX 전용 Dashboard는 Apple Silicon target에만 있다. vLLM target에서 그 uid로 링크하면
  // Grafana가 Dashboard not found를 보여 준다.
  const vllm = new URL(mainRuntimeDiagnosticsUrl('http://127.0.0.1:9411', 'vllm-cuda', 1_700_000_000));
  assert.equal(vllm.pathname, '/d/service_overview');
  const mlx = new URL(mainRuntimeDiagnosticsUrl('http://127.0.0.1:9411', 'mlx-vlm', 1_700_000_000));
  assert.equal(mlx.pathname, '/d/main-runtime-health');
});

test('diagnostic links fail closed without a safe direct Grafana URL', () => {
  assert.equal(requestLogDiagnosticsUrl(null, 'req_1', 1_700_000_000), null);
  assert.equal(requestLogDiagnosticsUrl('javascript:alert(1)', 'req_1', 1_700_000_000), null);
  assert.equal(requestLogDiagnosticsUrl('http://127.0.0.1:9411', '   ', 1_700_000_000), null);
});
