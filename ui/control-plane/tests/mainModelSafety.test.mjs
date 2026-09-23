import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isMainModelOperationTerminal,
  mainModelOperationProgress,
  mainModelOperationStagePresentation,
  mainModelProfileImpact,
  mainModelProfileRequiresConfirmation,
  mainModelResourcePolicyLabel,
  mainModelProfileSwitchable,
  mainModelSwitchRequest,
} from '../src/mainModelSafety.ts';

function profile(
  technicalStatus = 'compatible',
  qualificationStatus = 'verified',
  overrides = {},
) {
  return {
    id: 'candidate',
    display_name: 'Candidate',
    served_model_name: 'local-main',
    upstream_model_id: 'org/model',
    revision: 'a'.repeat(40),
    compatibility: { status: technicalStatus },
    qualification: { status: qualificationStatus },
    capabilities: { deployed_input: ['text'] },
    gateway_policy: {},
    runtime_image: 'registry.example/model@sha256:' + 'b'.repeat(64),
    vram_fraction: 0.5,
    resource_variant: null,
    resource_variants: [],
    active: false,
    ...overrides,
  };
}

test('qualification alone controls explicit confirmation', () => {
  assert.equal(mainModelProfileRequiresConfirmation(profile('compatible', 'verified')), false);
  assert.equal(mainModelProfileRequiresConfirmation(profile('compatible', 'unverified')), true);
  assert.equal(mainModelProfileRequiresConfirmation(profile('unknown', 'unverified')), true);
});

test('compatibility and active state control switchability', () => {
  assert.equal(mainModelProfileSwitchable(profile('incompatible', 'unverified')), false);
  assert.equal(
    mainModelProfileSwitchable(profile('compatible', 'verified', { active: true })),
    false,
  );
  assert.equal(mainModelProfileSwitchable(profile('unknown', 'unverified')), true);
  assert.throws(() => mainModelSwitchRequest(profile('incompatible', 'unverified'), true));
});

test('switch request carries qualification confirmation and terminal states', () => {
  assert.deepEqual(mainModelSwitchRequest(profile('compatible', 'unverified'), true), {
    profile: 'candidate',
    confirm_unverified: true,
  });
  assert.throws(() => mainModelSwitchRequest(profile('unknown', 'unverified'), false));
  assert.deepEqual(mainModelSwitchRequest(profile('unknown', 'unverified'), true), {
    profile: 'candidate',
    confirm_unverified: true,
  });
  assert.deepEqual(mainModelSwitchRequest(profile('compatible', 'verified'), false), {
    profile: 'candidate',
    confirm_unverified: false,
  });
  assert.equal(isMainModelOperationTerminal({ status: 'validating' }), false);
  assert.equal(isMainModelOperationTerminal({ status: 'completed' }), true);
  assert.equal(isMainModelOperationTerminal({ status: 'failed' }), true);
  assert.equal(isMainModelOperationTerminal({ status: 'rollback_failed' }), true);
});


test('resource policy presentation preserves the selected variant without inferring hardware support', () => {
  const reference = mainModelResourcePolicyLabel(profile());
  const override = mainModelResourcePolicyLabel(profile('compatible', 'verified', {
    resource_variant: 'rtx4090-24gb',
    resource_variants: ['rtx4090-24gb'],
  }));

  assert.notEqual(reference, override);
  assert.equal(override.includes('rtx4090-24gb'), true);
});

test('profile impact compares operator-visible switch differences without inferring hardware support', () => {
  const current = profile('compatible', 'verified', {
    capabilities: { deployed_input: ['text', 'image', 'audio'] },
    vram_fraction: 0.5,
  });
  const target = profile('unknown', 'unverified', {
    capabilities: { deployed_input: ['text', 'image', 'video'] },
    resource_variant: 'rtx4090-24gb',
    vram_fraction: 0.62,
  });

  assert.deepEqual(mainModelProfileImpact(current, target), {
    addedInputs: ['video'],
    removedInputs: ['audio'],
    resourcePolicyChanged: true,
    vramFractionDelta: 0.12,
    compatibilityChanged: true,
    qualificationChanged: true,
  });
});

test('profile impact reports an unchanged operator contract when visible fields match', () => {
  const current = profile();
  const target = profile();

  assert.deepEqual(mainModelProfileImpact(current, target), {
    addedInputs: [],
    removedInputs: [],
    resourcePolicyChanged: false,
    vramFractionDelta: 0,
    compatibilityChanged: false,
    qualificationChanged: false,
  });
});

test('operation stages expose operator-facing progress meaning', () => {
  const preparing = mainModelOperationProgress({ status: 'preparing', stage: 'preparing' });
  assert.deepEqual(
    preparing.map((item) => [item.stage, item.state]),
    [
      ['pending', 'complete'],
      ['preparing', 'current'],
      ['draining', 'pending'],
      ['stopping', 'pending'],
      ['starting', 'pending'],
      ['validating', 'pending'],
    ],
  );
  assert.equal(
    mainModelOperationStagePresentation('validating').description.includes('canary'),
    true,
  );
  assert.deepEqual(
    mainModelOperationProgress({ status: 'rolling_back', stage: 'rolling_back' })
      .map((item) => [item.stage, item.state]),
    [['rolling_back', 'current']],
  );
  assert.deepEqual(
    mainModelOperationProgress({ status: 'failed', stage: 'validating' })
      .map((item) => [item.stage, item.state]),
    [
      ['pending', 'complete'],
      ['preparing', 'complete'],
      ['draining', 'complete'],
      ['stopping', 'complete'],
      ['starting', 'complete'],
      ['validating', 'failed'],
    ],
  );
  assert.equal(
    mainModelOperationProgress({ status: 'completed', stage: 'completed' })
      .every((item) => item.state === 'complete'),
    true,
  );
});
