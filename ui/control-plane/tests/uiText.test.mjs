import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_UI_LOCALE,
  capabilityPresentation,
  formatPercent,
} from '../src/uiText.ts';

test('operator UI defaults to the Korean locale policy', () => {
  assert.equal(DEFAULT_UI_LOCALE, 'ko-KR');
});

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

test('navigation composition remains server-capability driven rather than OS driven', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

  assert.match(source, /deployment\.features\.includes\('runtime_control'\)/);
  assert.match(source, /deployment\.features\.includes\('model_switching'\)/);
  assert.doesNotMatch(source, /deployment\.platform\s*===/);
  assert.doesNotMatch(source, /navigator\.platform|userAgent|process\.platform/);
});
