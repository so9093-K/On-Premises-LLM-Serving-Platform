import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Alert, Button, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { ApiError, fetchRuntimes, postPublicJson } from './api';
import { useAdminSession } from './auth/AdminSessionContext';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import type { PublicModel } from './chatSession';
import { useChatSession } from './ChatSessionContext';
import {
  buildEmbeddingRequest,
  embeddingCapableModels,
  embeddingDimensions,
  embeddingRuntimeState,
  EMBEDDINGS_PATH,
  formatVectorPreview,
  summarizeEmbeddingResponse,
  type EmbeddingMode,
  type EmbeddingResult,
} from './embeddingPlayground';
import { PlaygroundUnavailableNotice } from './PlaygroundUnavailableNotice';
import { PublicRequestExportPanel } from './PublicRequestExportPanel';
import type { PublicRequestRecord } from './publicRequestExport';
import { usePublicModels } from './publicModelsQuery';
import { buildRetrievalRequest, retrievalAvailable, RETRIEVAL_MAX_DOCUMENTS, RETRIEVAL_RERANK_PATH,
  RETRIEVAL_TOP_N_MAX, summarizeRetrievalResponse, type RetrievalRequest, type RetrievalResult } from './retrievalPlayground';

type RetrievalRun = { request: RetrievalRequest; result: RetrievalResult; payload: unknown; requestId: string | null };

type EmbeddingRun = {
  inputs: string[];
  result: EmbeddingResult;
  payload: unknown;
  requestId: string | null;
};

type EmbeddingFailure = {
  message: string;
  requestId: string | null;
};

const RUNTIME_NOTICE: Record<'starting' | 'stopped' | 'unavailable', string> = {
  stopped: '이 Embedding Runtime은 중지돼 있어 요청이 거부됩니다. 런타임과 GPU에서 시작한 뒤 요청하세요.',
  starting: '이 Embedding Runtime은 시작 중입니다. 준비가 끝난 뒤 요청하세요.',
  unavailable: '현재 자원 정책에서 이 Embedding Runtime을 사용할 수 없습니다.',
};

// 입력과 결과는 이 화면의 상태에만 둔다. 다른 메뉴나 작업 화면으로 이동하면 사라진다.
// preview는 Embedding을 제공하지 않는 배포에서 화면 구성과 입력 방식만 보여 준다.
// Chat 예제 갤러리처럼 기능은 발견할 수 있게 두고, 모델 선택과 실행만 막아 요청을 보내지 않는다.
export function EmbeddingPlayground({ features, preview = false }: { features: readonly string[]; preview?: boolean }) {
  const { apiKey, credentialRevision, apiKeyRejected, rejectApiKey } = useChatSession();
  const { token } = useAdminSession();
  const modelsQuery = usePublicModels(apiKey, credentialRevision);
  // Runtime 상태는 관리자 API의 보조 진단이다. 조회하지 못하면 안내만 생략하고 요청 판단은 Gateway가 한다.
  const runtimesQuery = useQuery({
    queryKey: ['runtime-control', 'runtimes', token === null ? 'anonymous' : 'authenticated'],
    queryFn: () => fetchRuntimes(token),
    enabled: features.includes('runtime_control'),
    retry: false,
    staleTime: 10_000,
  });
  const models = useMemo(
    () => embeddingCapableModels((modelsQuery.data?.data ?? []) as PublicModel[]),
    [modelsQuery.data],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<EmbeddingMode | 'rank'>('single');
  const [inputs, setInputs] = useState(['', '']);
  const [query, setQuery] = useState('');
  const [documents, setDocuments] = useState([{ id: 0, text: '' }, { id: 1, text: '' }, { id: 2, text: '' }]);
  const nextDocumentId = useRef(3);
  const [topN, setTopN] = useState('2');
  const [retrievalRun, setRetrievalRun] = useState<RetrievalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<EmbeddingRun | null>(null);
  const [failure, setFailure] = useState<EmbeddingFailure | null>(null);
  const [inputChangedSinceRequest, setInputChangedSinceRequest] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<PublicRequestRecord | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const model = selectedId === null ? models[0] ?? null : models.find((item) => item.id === selectedId) ?? null;
  const selectionUnavailable = selectedId !== null && model === null;
  const selectedModelKey = selectedId ?? model?.id;
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;
  const showRank = preview || features.includes('retrieval');
  const canRank = preview || (model !== null && retrievalAvailable(model, features));

  useEffect(() => {
    if (modelsQuery.isSuccess && selectedId === null && models.length > 0) setSelectedId(models[0].id);
  }, [modelsQuery.isSuccess, models, selectedId]);

  useEffect(() => {
    setRun(null);
    setRetrievalRun(null);
    setFailure(null);
    setLastRequest(null);
    setInputError(null);
    setInputChangedSinceRequest(false);
    setBusy(false);
    return () => abortRef.current?.abort();
  }, [selectedModelKey, mode]);

  useEffect(() => {
    if (mode === 'rank' && model !== null && !canRank) setMode('single');
  }, [mode, canRank, model]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (preview || model === null || modelsQuery.isError || busy) return;
    if (mode === 'rank' && !canRank) return;
    const embedding = mode === 'rank' ? null : buildEmbeddingRequest(model, mode, inputs);
    const retrieval = mode === 'rank' ? buildRetrievalRequest(model, query, documents.map((item) => item.text), topN) : null;
    const body = retrieval?.body ?? embedding?.body;
    const error = retrieval?.error ?? embedding?.error ?? null;
    setInputError(error);
    if (!body) return;
    // 한 번 직렬화한 문자열을 전송과 "코드로 사용하기"에 함께 쓴다.
    const requestJson = JSON.stringify(body);
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setInputChangedSinceRequest(false);
    setRun(null);
    setRetrievalRun(null);
    setFailure(null);
    const path = retrieval ? RETRIEVAL_RERANK_PATH : EMBEDDINGS_PATH;
    setLastRequest({ kind: retrieval ? 'retrieval' : 'embeddings', path, requestJson });
    try {
      const { payload, requestId } = await postPublicJson(apiKey, path, requestJson, controller.signal);
      if (controller.signal.aborted) return;
      if (retrieval?.body) {
        const summary = summarizeRetrievalResponse(payload, retrieval.body);
        if (summary.error !== null) setFailure({ message: summary.error, requestId });
        else setRetrievalRun({ request: retrieval.body, result: summary.result, payload, requestId });
      } else if (embedding?.body) {
        const summary = summarizeEmbeddingResponse(payload, embedding.body);
        if (summary.error !== null) setFailure({ message: summary.error, requestId });
        else setRun({ inputs: Array.isArray(embedding.body.input) ? [...embedding.body.input] : [embedding.body.input], result: summary.result, payload, requestId });
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 401) rejectApiKey();
      setRun(null);
      setFailure({
        message: apiErrorMessage(reason, '요청에 실패했습니다.'),
        requestId: reason instanceof ApiError ? reason.requestId : null,
      });
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setBusy(false);
      }
    }
  }

  if (!preview && modelsQuery.isPending) {
    return <div className="inline-loading"><Spinner size="md" aria-label="모델 목록 불러오는 중" /> 모델 목록을 불러오는 중…</div>;
  }
  if (!preview && model === null && selectedId === null && modelsQuery.isSuccess) {
    return needsKey ? null : <Alert isInline variant="warning" title="Embedding을 지원하는 공개 모델이 없습니다." />;
  }

  const dimensions = model ? embeddingDimensions(model) : [];
  const runtime = model && !preview ? embeddingRuntimeState(model, runtimesQuery.data) : null;
  return (
    <section className="playground-workspace" aria-labelledby="embedding-workspace-title">
      <div className="playground-panel-heading">
        <div>
          <h2 id="embedding-workspace-title">Embedding</h2>
          <p>텍스트를 벡터로 변환하고 문장의 유사도를 비교합니다.{showRank ? ' 질문에 가까운 문서를 관련도순으로 확인할 수 있습니다.' : ''}</p>
        </div>
      </div>

      {preview ? <PlaygroundUnavailableNotice label="Embedding" preview /> : null}

      {!preview && modelsQuery.isError && !needsKey ? (
        <Alert isInline variant="danger" title="모델 목록을 불러오지 못했습니다.">
          <p>{apiErrorMessage(modelsQuery.error)} 입력과 마지막 결과를 유지했습니다. 모델 정보를 다시 확인한 뒤 실행하세요.</p>
          <Button variant="secondary" isDisabled={modelsQuery.isFetching}
            onClick={() => { void modelsQuery.refetch(); }}>모델 정보 다시 조회</Button>
        </Alert>
      ) : null}
      {!preview && selectionUnavailable ? (
        <Alert isInline variant="warning" title="이전에 선택한 Embedding 모델을 사용할 수 없습니다.">
          <p>입력과 마지막 결과를 유지했습니다. 사용할 모델을 직접 선택하세요.</p>
          <Button variant="secondary" isDisabled={modelsQuery.isFetching}
            onClick={() => { void modelsQuery.refetch(); }}>모델 목록 새로고침</Button>
        </Alert>
      ) : null}

      <form className="playground-form" onSubmit={(event) => { void submit(event); }}>
        <div className="playground-form-row">
          <div className="chat-model-selection">
            <label htmlFor="embedding-model">Embedding 모델</label>
            {!preview && (models.length > 0 || selectedId !== null) ? (
              <select
                id="embedding-model"
                value={selectedId ?? model?.id ?? ''}
                disabled={busy}
                onChange={(event) => setSelectedId(event.currentTarget.value)}
              >
                {selectionUnavailable ? <option value={selectedId ?? ''} disabled>{selectedId} · 사용 불가</option> : null}
                {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
              </select>
            ) : (
              <select id="embedding-model" disabled>
                <option>제공하는 배포에서 선택</option>
              </select>
            )}
          </div>
          <span className="playground-hint">
            {preview ? '모델 차원은 Embedding 모델이 있을 때 표시됩니다.'
              : dimensions.length ? `${dimensions.map((value) => value.toLocaleString()).join(' · ')}차원` : '차원 정보 없음'}
          </span>
        </div>

        {runtime && runtime.state !== 'active' ? (
          <Alert isInline variant="warning" title={`${runtime.serviceKey} Runtime: ${runtime.state === 'stopped' ? '중지됨' : runtime.state === 'starting' ? '시작 중' : '사용 불가'}`}>
            {RUNTIME_NOTICE[runtime.state]}
            {runtime.state === 'stopped' ? <> <Link to="/runtimes">런타임과 GPU로 이동 →</Link></> : null}
          </Alert>
        ) : null}

        <fieldset className="playground-choice" disabled={busy}>
          <legend>작업 선택 · 벡터 변환과 문서 관련도 분석</legend>
          <label>
            <input type="radio" name="embedding-mode" checked={mode === 'single'} onChange={() => setMode('single')} />
            텍스트 변환
          </label>
          <label>
            <input type="radio" name="embedding-mode" checked={mode === 'compare'} onChange={() => setMode('compare')} />
            두 문장 유사도
          </label>
          {showRank ? (
            <label>
              <input type="radio" name="embedding-mode" checked={mode === 'rank'} disabled={!canRank} onChange={() => setMode('rank')} />
              문서 관련도 순위
            </label>
          ) : null}
        </fieldset>
        {showRank && !canRank ? <p className="playground-hint">현재 모델은 문서 관련도 순위를 지원하지 않습니다. 지원 모델을 선택하면 사용할 수 있습니다.</p> : null}

        {mode === 'rank' ? (
          <div className="playground-retrieval-inputs">
            <div className="playground-retrieval-query">
              <div className="playground-field">
                <label htmlFor="retrieval-query">검색 질문</label>
                <textarea id="retrieval-query" rows={3} value={query} disabled={busy} onChange={(event) => { setQuery(event.currentTarget.value); setInputChangedSinceRequest(true); }} placeholder="GPU 메모리 부족 원인" />
              </div>
              <div className="playground-field">
                <label htmlFor="retrieval-top-n">상위 결과 개수</label>
                <input id="retrieval-top-n" type="number" min={1} max={RETRIEVAL_TOP_N_MAX} step={1} value={topN} disabled={busy} onChange={(event) => { setTopN(event.currentTarget.value); setInputChangedSinceRequest(true); }} />
              </div>
            </div>
            <div className="playground-retrieval-documents" role="group" aria-label="후보 문서">
              {documents.map((item, index) => (
                <div className="playground-field" key={item.id}>
                  <div className="playground-document-heading">
                    <label htmlFor={`retrieval-document-${item.id}`}>문서 {index + 1}</label>
                    <Button size="sm" variant="link" isDisabled={busy || documents.length <= 1} onClick={() => { setDocuments((current) => current.filter((entry) => entry.id !== item.id)); setInputChangedSinceRequest(true); }} aria-label={`문서 ${index + 1} 제거`}>제거</Button>
                  </div>
                  <textarea id={`retrieval-document-${item.id}`} rows={2} value={item.text} disabled={busy} onChange={(event) => {
                    const text = event.currentTarget.value;
                    setDocuments((current) => current.map((entry) => entry.id === item.id ? { ...entry, text } : entry));
                    setInputChangedSinceRequest(true);
                  }} />
                </div>
              ))}
              <Button size="sm" variant="secondary" isDisabled={busy || documents.length >= RETRIEVAL_MAX_DOCUMENTS} onClick={() => {
                const id = nextDocumentId.current++;
                setDocuments((current) => [...current, { id, text: '' }]);
                setInputChangedSinceRequest(true);
              }}>문서 추가</Button>
              <small className="playground-hint">최대 {RETRIEVAL_MAX_DOCUMENTS}개 문서</small>
            </div>
          </div>
        ) : (mode === 'compare' ? [0, 1] : [0]).map((index) => (
          <div className="playground-field" key={index}>
            <label htmlFor={`embedding-input-${index}`}>{mode === 'compare' ? `문장 ${index === 0 ? 'A' : 'B'}` : '텍스트'}</label>
            <textarea
              id={`embedding-input-${index}`}
              rows={mode === 'compare' ? 2 : 4}
              value={inputs[index]}
              disabled={busy}
              placeholder={index === 0 ? 'GPU 메모리가 부족해 모델 로딩이 실패했습니다.' : 'CUDA out of memory 오류가 발생했습니다.'}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setInputs((current) => current.map((item, position) => (position === index ? value : item)));
                setInputChangedSinceRequest(true);
              }}
            />
          </div>
        ))}

        <div className="chat-composer-actions">
          {inputError ? <p className="form-error" role="alert">{inputError}</p>
            : preview ? <span className="playground-hint">현재 배포에서는 실행할 수 없습니다.</span> : <span />}
          <Button type="submit" variant="primary" isDisabled={busy || preview || model === null || modelsQuery.isError}>
            {busy ? '요청 중…' : mode === 'rank' ? '관련도 순위 확인' : mode === 'compare' ? '유사도 계산' : '벡터 생성'}
          </Button>
        </div>
      </form>

      {inputChangedSinceRequest && (run !== null || retrievalRun !== null || failure !== null || lastRequest !== null) ? (
        <Alert isInline variant="info" title="이전 입력의 실행 결과입니다.">
          현재 입력이 마지막 요청 이후 변경됐습니다. 아래 결과와 코드 내보내기는 마지막으로 전송한 요청 기준입니다. 현재 입력을 반영하려면 다시 실행하세요.
        </Alert>
      ) : null}

      {failure ? (
        <Alert isInline variant="danger" title={mode === 'rank' ? '문서 관련도 요청이 완료되지 않았습니다.' : 'Embedding 요청이 완료되지 않았습니다.'}>
          <p>{failure.message}</p>
          {failure.requestId ? <p>Request ID: <code>{failure.requestId}</code></p> : null}
        </Alert>
      ) : null}

      {run ? (
        <section className="playground-result" aria-live="polite" aria-label="Embedding 결과">
          {run.result.similarity !== null ? (
            <div className="playground-result-headline">
              <span>Cosine similarity</span>
              <strong>{run.result.similarity.toFixed(4)}</strong>
              <small>같은 요청·같은 모델의 두 벡터로 계산했습니다. 정답 확률이 아닌 방향 유사도입니다.</small>
            </div>
          ) : null}
          <dl className="chat-facts">
            <div><dt>모델</dt><dd>{run.result.model}</dd></div>
            <div><dt>벡터</dt><dd>{run.result.vectors.length}개 · {run.result.vectors[0].dimensions.toLocaleString()}차원</dd></div>
            {run.result.usage?.totalTokens !== null && run.result.usage?.totalTokens !== undefined ? (
              <div><dt>토큰</dt><dd>{run.result.usage.totalTokens.toLocaleString()}</dd></div>
            ) : null}
            {run.requestId ? <div><dt>Request ID</dt><dd><code>{run.requestId}</code></dd></div> : null}
          </dl>
          <ol className="playground-vector-list">
            {run.result.vectors.map((vector) => (
              <li key={vector.index}>
                <span className="playground-vector-input">{run.inputs[vector.index]}</span>
                <code className="playground-vector-preview">{formatVectorPreview(vector.preview, vector.dimensions)}</code>
                <small>L2 norm {vector.norm.toFixed(4)}</small>
              </li>
            ))}
          </ol>
          <details className="playground-raw">
            <summary>원본 응답 JSON 보기</summary>
            <pre>{JSON.stringify(run.payload, null, 2)}</pre>
          </details>
        </section>
      ) : null}

      {retrievalRun ? (
        <section className="playground-result" aria-live="polite" aria-label="문서 관련도 결과">
          <h3>문서 관련도 순위</h3>
          <p className="playground-vector-input">검색 질문: {retrievalRun.request.query}</p>
          <p className="playground-hint">Cosine similarity가 높은 순서입니다. 점수는 정답 확률이 아닙니다.</p>
          <dl className="chat-facts">
            <div><dt>모델</dt><dd>{retrievalRun.result.model}</dd></div>
            <div><dt>후보 문서</dt><dd>{retrievalRun.request.documents.length}개</dd></div>
            <div><dt>반환 결과</dt><dd>{retrievalRun.result.results.length}개</dd></div>
            {retrievalRun.requestId ? <div><dt>Request ID</dt><dd><code>{retrievalRun.requestId}</code></dd></div> : null}
          </dl>
          {retrievalRun.result.results.length === 0 ? <p>반환된 문서가 없습니다.</p> : null}
          <ol className="playground-retrieval-results">
            {retrievalRun.result.results.map((item, rank) => (
              <li key={item.index}>
                <div className="playground-document-heading"><strong>{rank + 1}위 · 문서 {item.index + 1}</strong><span>관련도 {item.score.toFixed(4)}</span></div>
                <p>{item.document}</p>
              </li>
            ))}
          </ol>
          <details className="playground-raw"><summary>원본 응답 JSON 보기</summary><pre>{JSON.stringify(retrievalRun.payload, null, 2)}</pre></details>
        </section>
      ) : null}

      {lastRequest && !busy ? <PublicRequestExportPanel key={lastRequest.kind} record={lastRequest} completed={(run !== null || retrievalRun !== null) && failure === null} /> : null}
    </section>
  );
}
