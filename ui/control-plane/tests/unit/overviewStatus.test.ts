import { describe, expect, it } from 'vitest';

import { gatewayReadinessSignals, unmanagedModelSummary } from '../../src/overviewSignals';
import { capabilityPresentation } from '../../src/uiText';

describe('전환 API가 없는 배포의 운영 개요', () => {
  it('Core는 외부 모델 관리가 아니라 모델이 없는 상태다', () => {
    expect(unmanagedModelSummary('none', 'static', 'external')).toContain('메인 모델 없음');
    expect(capabilityPresentation('model_switching', ['risk'], 'external', 'none').status).toBe('제공하지 않음');
    expect(capabilityPresentation('runtime_control', ['risk'], 'external', 'none').status).toBe('제공하지 않음');
  });

  it('실제로 외부가 관리하는 Runtime은 기존 운영 경계를 설명한다', () => {
    expect(unmanagedModelSummary('vllm-cuda', 'static', 'external')).toContain('외부');
    expect(capabilityPresentation('runtime_control', ['chat'], 'external', 'vllm-cuda').status).toBe('외부 관리');
  });

  it('Gateway가 필수 의존 서비스 미준비를 보고하면 주의 없음으로 두지 않는다', () => {
    const dependencies = [{ name: 'main_llm_vllm', message: 'MODEL_UNAVAILABLE: Upstream unavailable: local-main' }];
    const [signal, ...rest] = gatewayReadinessSignals({ required_not_ready_dependencies: ['main_llm_vllm'], dependencies });
    expect(rest).toHaveLength(0);
    expect(signal.tone).toBe('warning');
    expect(signal.detail).toContain('MODEL_UNAVAILABLE');
    expect(gatewayReadinessSignals({ required_not_ready_dependencies: [], dependencies })).toHaveLength(0);
  });
});
