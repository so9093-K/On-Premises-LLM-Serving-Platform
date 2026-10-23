import { useQuery } from '@tanstack/react-query';

import { fetchPublicModels } from './api';

// Playground의 모든 작업 화면이 같은 /v1/models 결과와 cache key를 공유한다. Main Model
// 전환 뒤 'public-models'를 무효화하면 Chat·Embedding 화면이 함께 갱신된다(ADR-0047).
export function usePublicModels(apiKey: string | null) {
  return useQuery({
    queryKey: ['public-models', apiKey],
    queryFn: () => fetchPublicModels(apiKey),
    retry: false,
    staleTime: 30_000,
    // 인증 주체가 바뀌면 이전 키의 모델 목록을 새 키의 결과로 표시하지 않는다.
  });
}
