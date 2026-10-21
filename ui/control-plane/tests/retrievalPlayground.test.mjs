import assert from 'node:assert/strict';
import test from 'node:test';
import { buildRetrievalRequest, retrievalAvailable, RETRIEVAL_MAX_DOCUMENTS, summarizeRetrievalResponse } from '../src/retrievalPlayground.ts';

const model = { id: 'local-embed-ko', capabilities: ['embeddings', 'retrieval_rerank'], request_parameters: {} };
const request = { model: model.id, query: ' GPU 메모리 ', documents: ['무관한 문서', 'CUDA 오류\n메모리 부족'], top_n: 2 };
const response = { model: model.id, score_mode: 'dense_cosine', results: [
  { index: 1, document: request.documents[1], score: 0.8 },
  { index: 0, document: request.documents[0], score: -0.1 },
] };

test('문서 순위는 배포 기능과 모델 capability가 모두 지원할 때 제공한다', () => {
  assert.equal(retrievalAvailable(model, ['embeddings', 'retrieval']), true);
  assert.equal(retrievalAvailable(model, ['embeddings']), false);
  assert.equal(retrievalAvailable({ ...model, capabilities: ['embeddings'] }, ['retrieval']), false);
});

test('질문·다중 행 문서의 원문을 보존하고 공개 요청 한도를 따른다', () => {
  assert.deepEqual(buildRetrievalRequest(model, request.query, request.documents, '2').body, request);
  for (const args of [
    [model, ' ', request.documents, '2'],
    [model, request.query, [''], '2'],
    [model, request.query, [], '2'],
    [model, request.query, Array(RETRIEVAL_MAX_DOCUMENTS + 1).fill('문서'), '2'],
    [model, request.query, request.documents, '0'],
    [model, request.query, request.documents, '33'],
    [model, request.query, request.documents, '1.5'],
    [{ ...model, capabilities: ['embeddings'] }, request.query, request.documents, '2'],
  ]) assert.equal(buildRetrievalRequest(...args).body, null);
});

test('응답의 순위와 원본 문서 인덱스를 보존하고 빈 결과도 표시할 수 있다', () => {
  const summary = summarizeRetrievalResponse(response, request);
  assert.equal(summary.error, null);
  assert.deepEqual(summary.result.results, response.results);
  assert.deepEqual(summarizeRetrievalResponse({ ...response, results: [] }, request).result.results, []);
});

test('다른 모델·문서, 중복 인덱스, 비정상 점수·정렬·반환 개수는 성공 결과로 표시하지 않는다', () => {
  for (const candidate of [
    null, { ...response, model: 'local-embed' }, { ...response, score_mode: 'other' },
    { ...response, results: [...response.results].reverse() },
    { ...response, results: [response.results[0], response.results[0]] },
    { ...response, results: [{ ...response.results[0], document: '다른 문서' }] },
    { ...response, results: [{ ...response.results[0], index: 9 }] },
    { ...response, results: [{ ...response.results[0], score: Number.NaN }] },
  ]) assert.equal(summarizeRetrievalResponse(candidate, request).result, null);
  assert.equal(summarizeRetrievalResponse(response, { ...request, top_n: 1 }).result, null);
});
