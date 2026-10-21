import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  NAVIGATION_GROUPS,
  NAVIGATION_SECTIONS,
  visibleNavigationSections,
  visiblePlaygroundWorkspaces,
} from '../src/navigation.ts';
import { configurationGroupLabel, gpuBudgetAccessibilityLabel, t } from '../src/uiText.ts';

const paths = (features) => visibleNavigationSections(features).map((section) => section.path);
const workspaces = (features) => visiblePlaygroundWorkspaces(features).map((workspace) => workspace.path);

function deploymentTargetFeatures() {
  const yaml = readFileSync(new URL('../../../configs/deployment_targets.yaml', import.meta.url), 'utf8');
  const targets = {};
  for (const block of yaml.split(/(?=^  [a-z0-9-]+:$)/m).slice(1)) {
    const name = block.match(/^  ([a-z0-9-]+):$/m)[1];
    const features = block.split(/^    features:$/m)[1] ?? '';
    targets[name] = [...features.matchAll(/^      ([a-z_]+): true$/gm)].map((match) => match[1]);
  }
  return targets;
}

test('target features determine visible menu and directly accessible routes', () => {
  assert.deepEqual(paths([]), ['/', '/operations', '/configuration']);
  assert.deepEqual(paths(['chat']), ['/', '/operations', '/configuration', '/playground']);
  assert.deepEqual(
    paths(['model_switching', 'runtime_control', 'chat']),
    ['/', '/main-model', '/runtimes', '/operations', '/configuration', '/playground'],
  );
  assert.equal(new Set(NAVIGATION_SECTIONS.map((section) => section.path)).size, NAVIGATION_SECTIONS.length);
  for (const section of NAVIGATION_SECTIONS) {
    assert.ok(NAVIGATION_GROUPS.includes(section.group));
    assert.ok(t(section.labelKey));
    assert.ok(t(`navGroup.${section.group}`));
  }
});

test('Playground opens for any public request feature and shows only the deployed workspaces', () => {
  // Chat이 없는 Core도 PII·Secret Risk를 Playground에서 확인할 수 있어야 한다.
  const expected = {
    'linux-core': ['risk'],
    'linux-cpu-static': ['chat', 'risk'],
    'linux-cpu-managed': ['chat', 'risk'],
    'linux-adaptive': ['chat', 'risk'],
    'linux-nvidia-dynamic': ['chat', 'embeddings', 'risk'],
    'linux-nvidia-static': ['chat', 'risk'],
    'macos-metal-static': ['chat', 'risk'],
  };
  const targets = deploymentTargetFeatures();
  assert.deepEqual(Object.keys(targets).sort(), Object.keys(expected).sort());
  for (const [target, features] of Object.entries(targets)) {
    assert.deepEqual(workspaces(features), expected[target], target);
    assert.ok(paths(features).includes('/playground'), target);
  }
  assert.deepEqual(workspaces(['runtime_control', 'model_switching']), []);
  assert.equal(paths(['runtime_control', 'model_switching']).includes('/playground'), false);
});

test('operator-facing configuration group labels cover server-owned writable groups', () => {
  const yaml = readFileSync(new URL('../../../configs/configuration_schema.yaml', import.meta.url), 'utf8');
  const writableEntries = yaml.split(/(?=^  - key: )/m)
    .filter((entry) => /^    control_surface: configuration$/m.test(entry));
  const groups = new Set(writableEntries.map((entry) => entry.match(/^    group: (.+)$/m)?.[1]));
  assert.ok(groups.size > 0);
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
