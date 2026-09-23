import assert from 'node:assert/strict';
import test from 'node:test';

import { mainModelOverviewSignals } from '../src/overviewSignals.ts';

test('an intentionally stopped Main Model is informational rather than an incident', () => {
  const signals = mainModelOverviewSignals({
    gate: 'closed',
    runtime_state: 'stopped',
    observed_runtime: null,
  });

  assert.deepEqual(
    signals.map((signal) => [signal.key, signal.tone]),
    [['main-model-stopped', 'info']],
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
