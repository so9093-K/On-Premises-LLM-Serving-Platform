import { describe, expect, it } from 'vitest';
import { publicModelsQueryKey } from '../../src/publicModelsQuery';

describe('공개 모델 조회 캐시 인증 경계', () => {
  it('API 키 문자열이 Query Cache 식별자에 포함되지 않는다', () => {
    const first = publicModelsQueryKey(101);
    const second = publicModelsQueryKey(102);

    expect(first).toEqual(['public-models', 101]);
    expect(second).toEqual(['public-models', 102]);
    expect(first).not.toEqual(second);
    expect(JSON.stringify(first)).not.toContain('secret');
  });
});
