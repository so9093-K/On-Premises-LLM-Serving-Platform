import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { NAVIGATION_GROUPS, NAVIGATION_SECTIONS, visibleNavigationSections } from '../src/navigation.ts';
import { configurationGroupLabel, gpuBudgetAccessibilityLabel, t } from '../src/uiText.ts';

const paths = (features) => visibleNavigationSections(features).map((section) => section.path);

test('target features determine visible menu and directly accessible routes', () => {
  assert.deepEqual(paths([]), ['/', '/operations', '/configuration']);
  assert.deepEqual(paths(['chat']), ['/', '/operations', '/configuration', '/chat']);
  assert.deepEqual(
    paths(['model_switching', 'runtime_control', 'chat']),
    ['/', '/main-model', '/runtimes', '/operations', '/configuration', '/chat'],
  );
  assert.equal(new Set(NAVIGATION_SECTIONS.map((section) => section.path)).size, NAVIGATION_SECTIONS.length);
  for (const section of NAVIGATION_SECTIONS) {
    assert.ok(NAVIGATION_GROUPS.includes(section.group));
    assert.ok(t(section.labelKey));
    assert.ok(t(`navGroup.${section.group}`));
  }
});

test('operator-facing configuration group labels cover server-owned writable groups', () => {
  const yaml = readFileSync(new URL('../../../configs/configuration_schema.yaml', import.meta.url), 'utf8');
  const writableEntries = yaml.split(/(?=^  - key: )/m)
    .filter((entry) => /^    control_surface: configuration$/m.test(entry));
  const groups = new Set(writableEntries.map((entry) => entry.match(/^    group: (.+)$/m)?.[1]));
  assert.deepEqual([...groups].sort(), ['retrieval', 'streaming']);
  for (const group of groups) {
    assert.ok(group);
    assert.notEqual(configurationGroupLabel(group), group);
  }
  assert.equal(configurationGroupLabel('future_group'), 'future_group');
});

test('GPU admission is labeled as policy reservation rather than observed VRAM', () => {
  assert.equal(gpuBudgetAccessibilityLabel(0.76, 0.9), '정책상 GPU 예약 76%, 예약 상한 90%');
  assert.doesNotMatch(gpuBudgetAccessibilityLabel(0.76, 0.9), /GPU 사용/);
});
