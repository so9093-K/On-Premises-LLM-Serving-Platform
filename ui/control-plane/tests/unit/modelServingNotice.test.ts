import { describe, expect, it } from 'vitest';
import { modelRuntimeLabel, modelServingNotice } from '../../src/uiText';
import { PUBLIC_MODELS_REFRESH_MS, publicModelsQueryKey } from '../../src/publicModelsQuery';

describe('공개 모델 변경과 제어 상태의 사용자 계약', () => {
  it('계약이 활성 상태이거나 외부 Runtime에 정책 정보가 없을 때 요청을 제한하지 않는다', () => {
    expect(modelServingNotice('active')).toBeNull();
    expect(modelServingNotice(undefined)).toBeNull();
  });

  it('Controller 장애·요청 Gate 차단·미검증을 정상 상태로 표시하지 않는다', () => {
    for (const status of ['controller_unavailable', 'gate_closed', 'unverified', 'future_state']) {
      const notice = modelServingNotice(status);
      expect(notice?.title.length).toBeGreaterThan(5);
      expect(notice?.description.length).toBeGreaterThan(5);
    }
    expect(modelRuntimeLabel('unknown')).toBe('실행 엔진 확인 불가');
  });

  it('공개 모델 조회 주기와 인증 세션 캐시 경계를 유지한다', () => {
    expect(PUBLIC_MODELS_REFRESH_MS).toBeGreaterThanOrEqual(10_000);
    expect(PUBLIC_MODELS_REFRESH_MS).toBeLessThanOrEqual(30_000);
    expect(publicModelsQueryKey(1)).not.toEqual(publicModelsQueryKey(2));
  });
});
