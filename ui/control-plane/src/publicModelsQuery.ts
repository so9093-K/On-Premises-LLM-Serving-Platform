import { useQuery } from '@tanstack/react-query';

import { fetchPublicModels } from './api';

export function publicModelsQueryKey(credentialRevision: number): readonly [string, number] {
  return ['public-models', credentialRevision];
}

// Playground의 모든 작업 화면이 같은 /v1/models 결과와 cache key를 공유한다. Main Model
// 전환 뒤 'public-models'를 무효화하면 Chat·Embedding 화면이 함께 갱신된다(ADR-0047).
export function usePublicModels(apiKey: string | null, credentialRevision: number) {
  return useQuery({
    queryKey: publicModelsQueryKey(credentialRevision),
    queryFn: () => fetchPublicModels(apiKey),
    retry: false,
    staleTime: 30_000,
    // 인증 주체가 바뀌면 숫자 버전이 달라져 이전 키의 응답을 재사용하지 않는다.
  });
}
