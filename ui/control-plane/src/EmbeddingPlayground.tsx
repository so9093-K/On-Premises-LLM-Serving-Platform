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
import { usePublicModels } from './publicModelsQuery';

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
export function EmbeddingPlayground({ features }: { features: readonly string[] }) {
  const { apiKey, apiKeyRejected, rejectApiKey } = useChatSession();
  const { token } = useAdminSession();
  const modelsQuery = usePublicModels(apiKey);
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
  const [mode, setMode] = useState<EmbeddingMode>('single');
  const [inputs, setInputs] = useState(['', '']);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<EmbeddingRun | null>(null);
  const [failure, setFailure] = useState<EmbeddingFailure | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const model = models.find((item) => item.id === selectedId) ?? models[0] ?? null;
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;

  useEffect(() => () => abortRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (model === null || busy) return;
    const { body, error } = buildEmbeddingRequest(model, mode, inputs);
    setInputError(error);
    if (body === null) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const { payload, requestId } = await postPublicJson(apiKey, EMBEDDINGS_PATH, body, controller.signal);
      const summary = summarizeEmbeddingResponse(payload, body);
      if (summary.error !== null) {
        setRun(null);
        setFailure({ message: summary.error, requestId });
      } else {
        setRun({ inputs: Array.isArray(body.input) ? [...body.input] : [body.input], result: summary.result, payload, requestId });
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 401) rejectApiKey();
      setRun(null);
      setFailure({
        message: apiErrorMessage(reason, 'Embedding 요청에 실패했습니다.'),
        requestId: reason instanceof ApiError ? reason.requestId : null,
      });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  }

  if (modelsQuery.isPending) {
    return <div className="inline-loading"><Spinner size="md" aria-label="모델 목록 불러오는 중" /> 모델 목록을 불러오는 중…</div>;
  }
  if (modelsQuery.isError && !needsKey) {
    return (
      <Alert isInline variant="danger" title="모델 목록을 불러오지 못했습니다.">
        {apiErrorMessage(modelsQuery.error)}
      </Alert>
    );
  }
  if (model === null) {
    return needsKey ? null : <Alert isInline variant="warning" title="Embedding을 지원하는 공개 모델이 없습니다." />;
  }

  const dimensions = embeddingDimensions(model);
  const runtime = embeddingRuntimeState(model, runtimesQuery.data);
  return (
    <section className="playground-workspace" aria-labelledby="embedding-workspace-title">
      <div className="playground-panel-heading">
        <div>
          <h2 id="embedding-workspace-title">Embedding</h2>
          <p>텍스트를 벡터로 변환합니다. 두 문장 비교는 한 요청에서 같은 모델로 변환한 벡터끼리만 계산합니다.</p>
        </div>
      </div>

      <form className="playground-form" onSubmit={(event) => { void submit(event); }}>
        <div className="playground-form-row">
          <div className="chat-model-selection">
            <label htmlFor="embedding-model">Embedding 모델</label>
            <select
              id="embedding-model"
              value={model.id}
              disabled={busy}
              onChange={(event) => setSelectedId(event.currentTarget.value)}
            >
              {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
            </select>
          </div>
          <span className="playground-hint">
            {dimensions.length ? `${dimensions.map((value) => value.toLocaleString()).join(' · ')}차원` : '차원 정보 없음'}
          </span>
        </div>

        {runtime && runtime.state !== 'active' ? (
          <Alert isInline variant="warning" title={`${runtime.serviceKey} Runtime: ${runtime.state === 'stopped' ? '중지됨' : runtime.state === 'starting' ? '시작 중' : '사용 불가'}`}>
            {RUNTIME_NOTICE[runtime.state]}
            {runtime.state === 'stopped' ? <> <Link to="/runtimes">런타임과 GPU로 이동 →</Link></> : null}
          </Alert>
        ) : null}

        <fieldset className="playground-choice" disabled={busy}>
          <legend>작업</legend>
          <label>
            <input type="radio" name="embedding-mode" checked={mode === 'single'} onChange={() => setMode('single')} />
            텍스트 변환
          </label>
          <label>
            <input type="radio" name="embedding-mode" checked={mode === 'compare'} onChange={() => setMode('compare')} />
            두 문장 유사도
          </label>
        </fieldset>

        {(mode === 'compare' ? [0, 1] : [0]).map((index) => (
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
              }}
            />
          </div>
        ))}

        <div className="chat-composer-actions">
          {inputError ? <p className="form-error" role="alert">{inputError}</p> : <span />}
          <Button type="submit" variant="primary" isDisabled={busy}>
            {busy ? '변환 중…' : mode === 'compare' ? '유사도 계산' : '벡터 생성'}
          </Button>
        </div>
      </form>

      {failure ? (
        <Alert isInline variant="danger" title="Embedding 요청이 완료되지 않았습니다.">
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
    </section>
  );
}
