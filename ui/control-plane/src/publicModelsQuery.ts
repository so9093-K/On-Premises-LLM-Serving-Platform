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
    // API 키를 바꿔 다시 불러오는 동안 작업 화면이 사라지지 않게 이전 목록을 유지한다.
    placeholderData: (previous) => previous,
  });
}
