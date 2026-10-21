import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildEmbeddingRequest,
  cosineSimilarity,
  embeddingCapableModels,
  embeddingDimensions,
  embeddingRuntimeState,
  formatVectorPreview,
  summarizeEmbeddingResponse,
} from '../src/embeddingPlayground.ts';

const embed = {
  id: 'local-embed-ko',
  backend: 'embedding_ko_vllm',
  capabilities: ['embeddings', 'retrieval_rerank'],
  request_parameters: { dimensions: { type: 'integer', enum: [1024] } },
};
const chat = { id: 'local-main', backend: 'vllm-cuda', capabilities: ['chat.completions'], request_parameters: {} };

function response(model, vectors) {
  return {
    object: 'list',
    model,
    data: vectors.map((embedding, index) => ({ object: 'embedding', index, embedding })),
    usage: { prompt_tokens: 7, total_tokens: 7 },
  };
}

test('only models that advertise embeddings are offered, with their public dimensions', () => {
  assert.deepEqual(embeddingCapableModels([chat, embed]).map((model) => model.id), ['local-embed-ko']);
  assert.deepEqual(embeddingDimensions(embed), [1024]);
  assert.deepEqual(embeddingDimensions({ ...embed, request_parameters: {} }), []);
});

test('comparison sends both sentences in one request so both vectors come from the same model', () => {
  assert.deepEqual(buildEmbeddingRequest(embed, 'single', ['안녕하세요', 'unused']).body, {
    model: 'local-embed-ko',
    input: '안녕하세요',
  });
  assert.deepEqual(buildEmbeddingRequest(embed, 'compare', ['문장 A', '문장 B']).body, {
    model: 'local-embed-ko',
    input: ['문장 A', '문장 B'],
  });
  assert.match(buildEmbeddingRequest(embed, 'compare', ['문장 A', '  ']).error, /두 문장/);
  assert.match(buildEmbeddingRequest(embed, 'single', ['']).error, /텍스트/);
  assert.match(buildEmbeddingRequest(chat, 'single', ['text']).error, /Embedding API/);
});

test('similarity is computed only from vectors of the validated response', () => {
  const request = { model: 'local-embed-ko', input: ['a', 'b'] };
  const { result } = summarizeEmbeddingResponse(response('local-embed-ko', [[1, 0, 0], [1, 0, 0]]), request);
  assert.equal(result.similarity, 1);
  assert.equal(result.vectors[0].dimensions, 3);
  assert.deepEqual(result.usage, { promptTokens: 7, totalTokens: 7 });

  assert.match(summarizeEmbeddingResponse(response('local-embed', [[1], [1]]), request).error, /model/);
  assert.match(summarizeEmbeddingResponse(response('local-embed-ko', [[1]]), request).error, /2개/);
  assert.match(summarizeEmbeddingResponse(response('local-embed-ko', [[1], ['x']]), request).error, /data\[1\]/);
  const single = summarizeEmbeddingResponse(response('local-embed-ko', [[0.5, 0.5]]), { model: 'local-embed-ko', input: 'a' });
  assert.equal(single.result.similarity, null);
});

test('cosine similarity rejects vectors that cannot be compared', () => {
  assert.equal(cosineSimilarity([1, 0], [0, 1]), 0);
  assert.equal(cosineSimilarity([1, 0], [1, 0, 0]), null);
  assert.equal(cosineSimilarity([0, 0], [1, 0]), null);
  assert.equal(cosineSimilarity([], []), null);
});

test('long vectors are previewed instead of listing every value', () => {
  assert.equal(formatVectorPreview([0.1, -0.2], 1024), '[0.1000, -0.2000, … 1022개 생략]');
  assert.equal(formatVectorPreview([0.1, -0.2], 2), '[0.1000, -0.2000]');
});

test('runtime state is matched through the public backend service id and never guessed', () => {
  const view = {
    runtimes: [
      { service_key: 'embedding', state: 'active' },
      { service_key: 'embedding_ko', state: 'stopped' },
    ],
    topology: [
      { service_key: 'embedding', service_id: 'embedding_vllm', available: true },
      { service_key: 'embedding_ko', service_id: 'embedding_ko_vllm', available: true },
    ],
  };
  assert.deepEqual(embeddingRuntimeState(embed, view), { serviceKey: 'embedding_ko', state: 'stopped' });
  assert.deepEqual(embeddingRuntimeState({ ...embed, backend: 'embedding_vllm' }, view), { serviceKey: 'embedding', state: 'active' });
  const unavailable = { ...view, topology: [{ service_key: 'embedding_ko', service_id: 'embedding_ko_vllm', available: false }] };
  assert.deepEqual(embeddingRuntimeState(embed, unavailable), { serviceKey: 'embedding_ko', state: 'unavailable' });
  // 관리자 상태를 읽지 못했거나 대응 Runtime이 없으면 안내하지 않는다.
  assert.equal(embeddingRuntimeState(embed, null), null);
  assert.equal(embeddingRuntimeState({ ...embed, backend: 'external' }, view), null);
});
