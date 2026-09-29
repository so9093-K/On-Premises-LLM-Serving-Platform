import assert from 'node:assert/strict';
import test from 'node:test';

import {
  capabilityPresentation,
  formatPercent,
  runtimeStateLabel,
} from '../src/uiText.ts';

test('capability presentation preserves semantic availability classes', () => {
  const externalControl = capabilityPresentation('runtime_control', ['chat'], 'external');
  const absentServing = capabilityPresentation('embeddings', ['chat'], 'external');
  const availableControl = capabilityPresentation(
    'runtime_control',
    ['runtime_control'],
    'platform',
  );

  assert.equal(externalControl.key, 'runtime_control');
  assert.equal(externalControl.tone, 'blue');
  assert.equal(absentServing.key, 'embeddings');
  assert.equal(absentServing.tone, 'grey');
  assert.equal(availableControl.key, 'runtime_control');
  assert.equal(availableControl.tone, 'green');
});

test('resource fractions are formatted as operator percentages', () => {
  assert.equal(formatPercent(0.76), '76%');
  assert.equal(formatPercent(undefined), '—');
});

test('container states from Docker never leak as raw English values', () => {
  for (const state of ['exited', 'paused', 'restarting', 'dead', 'not_found', 'unknown']) {
    assert.doesNotMatch(runtimeStateLabel(state), /^[a-z_]+$/);
  }
  assert.equal(runtimeStateLabel('error: connection refused'), '조회 실패');
});
