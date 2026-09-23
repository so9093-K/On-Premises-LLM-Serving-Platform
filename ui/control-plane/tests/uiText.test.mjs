import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_UI_LOCALE,
  capabilityPresentation,
  deploymentTargetLabel,
  formatPercent,
  runtimeStateLabel,
  t,
} from '../src/uiText.ts';

test('operator UI defaults to Korean while keeping an English fallback catalog', () => {
  assert.equal(DEFAULT_UI_LOCALE, 'ko-KR');
  assert.equal(t('nav.overview'), '개요');
  assert.equal(t('nav.overview', 'en-US'), 'Overview');
  assert.equal(t('nav.mainModel'), '메인 모델');
});

test('deployment target names preserve one product vocabulary across platforms', () => {
  assert.equal(
    deploymentTargetLabel('linux-nvidia-dynamic', 'fallback'),
    'Linux + NVIDIA · 플랫폼 관리형',
  );
  assert.equal(
    deploymentTargetLabel('macos-metal-static', 'fallback'),
    'macOS + Metal · 외부 메인 런타임',
  );
  assert.equal(deploymentTargetLabel('future-target', 'Future Target'), 'Future Target');
});

test('capability presentation distinguishes available, externally managed, and absent', () => {
  assert.deepEqual(
    capabilityPresentation('runtime_control', ['chat'], 'external'),
    {
      key: 'runtime_control',
      label: '런타임 제어',
      status: '외부 관리',
      detail: '이 실행 환경에서는 외부 또는 네이티브 런타임이 관리합니다.',
      tone: 'blue',
    },
  );
  assert.equal(
    capabilityPresentation('embeddings', ['chat'], 'external').status,
    '제공하지 않음',
  );
  assert.equal(
    capabilityPresentation('runtime_control', ['runtime_control'], 'platform').status,
    '사용 가능',
  );
});

test('status and resource values are presented for operators', () => {
  assert.equal(runtimeStateLabel('active'), '실행 중');
  assert.equal(runtimeStateLabel('verified'), '검증 완료');
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
