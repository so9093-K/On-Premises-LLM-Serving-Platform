import requestSchema from '../../../specs/schemas/retrieval_rerank_request.schema.json' with { type: 'json' };
import type { PublicModel } from './chatSession';

export const RETRIEVAL_RERANK_PATH = '/v1/retrieval/rerank';
export const RETRIEVAL_MAX_DOCUMENTS = requestSchema.properties.documents.maxItems;
export const RETRIEVAL_TOP_N_MAX = requestSchema.properties.top_n.maximum;

export type RetrievalRequest = { model: string; query: string; documents: string[]; top_n: number };
export type RetrievalResult = {
  model: string;
  scoreMode: 'dense_cosine';
  results: { index: number; document: string; score: number }[];
};

export function retrievalAvailable(model: PublicModel, features: readonly string[]): boolean {
  return features.includes('retrieval') && model.capabilities.includes('retrieval_rerank');
}

export function buildRetrievalRequest(
  model: PublicModel, query: string, documents: readonly string[], topN: string,
): { body: RetrievalRequest; error: null } | { body: null; error: string } {
  const invalid = (error: string) => ({ body: null, error });
  if (!model.capabilities.includes('retrieval_rerank')) return invalid('현재 모델은 문서 관련도 순위를 지원하지 않습니다.');
  if (!query.trim()) return invalid('검색 질문을 입력하세요.');
  if (documents.length < 1 || documents.length > RETRIEVAL_MAX_DOCUMENTS) {
    return invalid(`후보 문서는 1~${RETRIEVAL_MAX_DOCUMENTS}개까지 입력할 수 있습니다.`);
  }
  if (documents.some((document) => !document.trim())) return invalid('후보 문서를 모두 입력하거나 빈 항목을 제거하세요.');
  if (!/^\d+$/.test(topN) || Number(topN) < 1 || Number(topN) > RETRIEVAL_TOP_N_MAX) {
    return invalid(`반환 개수는 1~${RETRIEVAL_TOP_N_MAX} 사이의 정수여야 합니다.`);
  }
  return { body: { model: model.id, query, documents: [...documents], top_n: Number(topN) }, error: null };
}

// 응답 순서는 Gateway가 소유한다. 다른 문서·모델의 결과를 표시하거나 화면에서 재정렬하지 않는다.
export function summarizeRetrievalResponse(
  payload: unknown, request: RetrievalRequest,
): { result: RetrievalResult; error: null } | { result: null; error: string } {
  const invalid = () => ({ result: null, error: '문서 관련도 응답이 요청한 모델·문서·순위와 일치하지 않습니다.' });
  if (typeof payload !== 'object' || payload === null) return invalid();
  const body = payload as Record<string, unknown>;
  if (body.model !== request.model || body.score_mode !== 'dense_cosine' || !Array.isArray(body.results)
    || body.results.length > Math.min(request.top_n, request.documents.length)) return invalid();
  const seen = new Set<number>();
  const results: RetrievalResult['results'] = [];
  for (const item of body.results) {
    if (typeof item !== 'object' || item === null) return invalid();
    const { index, document, score } = item as Record<string, unknown>;
    if (typeof index !== 'number' || !Number.isInteger(index) || index < 0 || index >= request.documents.length
      || seen.has(index) || document !== request.documents[index] || typeof score !== 'number' || !Number.isFinite(score)
      || (results.length > 0 && score > results.at(-1)!.score)) return invalid();
    seen.add(index);
    results.push({ index, document: document as string, score });
  }
  return { result: { model: request.model, scoreMode: 'dense_cosine', results }, error: null };
}
