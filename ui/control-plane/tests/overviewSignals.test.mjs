import assert from 'node:assert/strict';
import test from 'node:test';

import { mainModelOverviewSignals } from '../src/overviewSignals.ts';

test('an intentionally stopped Main Model is informational rather than an incident', () => {
  assert.deepEqual(
    mainModelOverviewSignals({ gate: 'closed', runtime_state: 'stopped', observed_runtime: null }),
    [{
      key: 'main-model-stopped',
      tone: 'info',
      title: '메인 모델이 중지된 상태입니다.',
      detail: '의도적으로 중지한 상태일 수 있으므로 장애로 단정하지 않습니다. 필요하면 메인 모델 화면에서 현재 상태와 최근 작업을 확인하세요.',
    }],
  );
});

test('active control state never hides a closed gate or unhealthy observation', () => {
  const signals = mainModelOverviewSignals({
    gate: 'closed',
    runtime_state: 'active',
    observed_runtime: { status: 'starting', health: 'unhealthy', error: 'probe failed' },
  });

  assert.deepEqual(signals.map((signal) => [signal.key, signal.tone]), [
    ['main-model-gate', 'warning'],
    ['main-model-observed-state', 'warning'],
  ]);
  assert.equal(signals[1].detail.includes('probe failed'), true);
});

test('ready and healthy active runtime produces no operator attention signal', () => {
  assert.deepEqual(mainModelOverviewSignals({
    gate: 'open',
    runtime_state: 'active',
    observed_runtime: { status: 'ready', health: 'healthy' },
  }), []);
});

test('state recovery error is preserved even when the runtime is intentionally stopped', () => {
  const signals = mainModelOverviewSignals({
    gate: 'closed',
    runtime_state: 'stopped',
    state_recovery_error: 'journal mismatch',
    observed_runtime: null,
  });
  assert.deepEqual(signals.map((signal) => signal.key), [
    'main-model-state-recovery',
    'main-model-stopped',
  ]);
});
