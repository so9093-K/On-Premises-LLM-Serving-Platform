import { useQuery } from '@tanstack/react-query';

import { fetchPublicModels } from './api';

// API 키 문자열 대신 탭 내 인증 세션 버전을 캐시 식별자로 사용한다.
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
  });
}
