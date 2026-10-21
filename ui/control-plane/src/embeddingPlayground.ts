import type { PublicModel } from './chatSession';

// Embedding 작업 화면의 순수 로직. 모델·차원의 authority는 /v1/models이며, 요청 본문은
// 공개 /v1/embeddings 계약을 그대로 만든다. 화면은 이 결과를 표시만 한다.
export const EMBEDDINGS_PATH = '/v1/embeddings';
export const EMBEDDING_PREVIEW_VALUES = 8;

export type EmbeddingMode = 'single' | 'compare';

export type EmbeddingRequestBody = {
  model: string;
  input: string | [string, string];
};

export type EmbeddingVectorSummary = {
  index: number;
  dimensions: number;
  preview: number[];
  norm: number;
};

export type EmbeddingUsage = {
  promptTokens: number | null;
  totalTokens: number | null;
};

export type EmbeddingResult = {
  model: string;
  vectors: EmbeddingVectorSummary[];
  usage: EmbeddingUsage | null;
  // compare 요청에서만 값이 있다. 같은 응답의 두 벡터, 즉 같은 모델의 벡터끼리만 비교한다.
  similarity: number | null;
};

export function embeddingCapableModels(models: readonly PublicModel[]): PublicModel[] {
  return models.filter((model) => model.capabilities.includes('embeddings'));
}

export function embeddingDimensions(model: PublicModel): number[] {
  const spec = model.request_parameters.dimensions;
  const values = spec && Array.isArray(spec.enum) ? spec.enum : [];
  return values.filter((value): value is number => Number.isInteger(value) && value > 0);
}

export function buildEmbeddingRequest(
  model: PublicModel,
  mode: EmbeddingMode,
  inputs: readonly string[],
): { body: EmbeddingRequestBody; error: null } | { body: null; error: string } {
  if (!model.capabilities.includes('embeddings')) {
    return { body: null, error: '현재 모델은 Embedding API를 지원하지 않습니다.' };
  }
  const required = mode === 'compare' ? 2 : 1;
  const values = inputs.slice(0, required);
  if (values.length < required || values.some((value) => !value.trim())) {
    return {
      body: null,
      error: mode === 'compare' ? '비교할 두 문장을 모두 입력하세요.' : '변환할 텍스트를 입력하세요.',
    };
  }
  // 입력은 사용자가 쓴 그대로 보낸다. compare는 두 문장을 한 요청에 담아 같은 모델이
  // 같은 시점에 변환한 벡터만 비교하도록 보장한다.
  return {
    body: { model: model.id, input: mode === 'compare' ? [values[0], values[1]] : values[0] },
    error: null,
  };
}

function vectorNorm(vector: readonly number[]): number {
  return Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
}

export function cosineSimilarity(left: readonly number[], right: readonly number[]): number | null {
  if (left.length === 0 || left.length !== right.length) return null;
  const leftNorm = vectorNorm(left);
  const rightNorm = vectorNorm(right);
  if (leftNorm === 0 || rightNorm === 0) return null;
  let dot = 0;
  for (let index = 0; index < left.length; index += 1) dot += left[index] * right[index];
  return dot / (leftNorm * rightNorm);
}

function optionalCount(value: unknown): number | null {
  return Number.isInteger(value) && (value as number) >= 0 ? value as number : null;
}

export function summarizeEmbeddingResponse(
  payload: unknown,
  request: EmbeddingRequestBody,
): { result: EmbeddingResult; error: null } | { result: null; error: string } {
  const invalid = (detail: string) => ({ result: null, error: `Embedding 응답 형식이 올바르지 않습니다: ${detail}` });
  if (typeof payload !== 'object' || payload === null) return invalid('객체가 아닙니다.');
  const body = payload as Record<string, unknown>;
  if (body.model !== request.model) return invalid(`model이 요청한 ${request.model}과 다릅니다.`);
  const expectedCount = Array.isArray(request.input) ? request.input.length : 1;
  if (!Array.isArray(body.data) || body.data.length !== expectedCount) {
    return invalid(`data에 ${expectedCount}개의 벡터가 필요합니다.`);
  }
  const vectors: number[][] = [];
  for (const [position, item] of body.data.entries()) {
    const entry = typeof item === 'object' && item !== null ? item as Record<string, unknown> : {};
    const embedding = entry.embedding;
    if (entry.index !== position || !Array.isArray(embedding) || embedding.length === 0
      || !embedding.every((value) => typeof value === 'number' && Number.isFinite(value))) {
      return invalid(`data[${position}]는 순서가 맞는 숫자 벡터여야 합니다.`);
    }
    vectors.push(embedding as number[]);
  }
  const usage = typeof body.usage === 'object' && body.usage !== null
    ? body.usage as Record<string, unknown>
    : null;
  return {
    result: {
      model: request.model,
      vectors: vectors.map((vector, index) => ({
        index,
        dimensions: vector.length,
        preview: vector.slice(0, EMBEDDING_PREVIEW_VALUES),
        norm: vectorNorm(vector),
      })),
      usage: usage === null ? null : {
        promptTokens: optionalCount(usage.prompt_tokens),
        totalTokens: optionalCount(usage.total_tokens),
      },
      similarity: vectors.length === 2 ? cosineSimilarity(vectors[0], vectors[1]) : null,
    },
    error: null,
  };
}

export function formatVectorPreview(preview: readonly number[], dimensions: number): string {
  const values = preview.map((value) => value.toFixed(4)).join(', ');
  return dimensions > preview.length ? `[${values}, … ${dimensions - preview.length}개 생략]` : `[${values}]`;
}
