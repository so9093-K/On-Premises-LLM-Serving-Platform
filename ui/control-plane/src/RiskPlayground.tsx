import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert, Button } from '@patternfly/react-core';

import { ApiError, postPublicJson } from './api';
import { apiErrorMessage } from './apiFeedback';
import { useChatSession } from './ChatSessionContext';
import {
  availableRiskChecks,
  availableRiskExamples,
  buildRiskRequest,
  interpretRiskAssessment,
  MAX_RISK_PROMPT_CHARACTERS,
  riskCodeLabel,
  riskPromptLength,
  systemSignalLabel,
  type RiskCheckId,
  type RiskInterpretation,
} from './riskPlayground';

type RiskRun = {
  checkLabel: string;
  interpretation: RiskInterpretation;
  payload: unknown;
  requestId: string | null;
};

const VERDICT_TEXT: Record<RiskInterpretation['verdict'], { title: string; detail: string; tone: string }> = {
  signal_detected: {
    title: '위험 신호 탐지됨',
    detail: '탐지기는 위험 신호만 제공합니다. 허용·차단은 호출하는 서비스의 정책이 결정합니다.',
    tone: 'warning',
  },
  no_signal: {
    title: '탐지된 위험 신호 없음',
    detail: '검사가 완료됐고 시스템 신호도 없습니다. 탐지 범위 밖의 위험이 없다는 보증은 아닙니다.',
    tone: 'success',
  },
  incomplete: {
    title: '검사가 완료되지 않음',
    detail: 'HTTP 200이어도 검사가 완료되지 않았거나 시스템 신호가 있으면 미탐지로 해석하지 않습니다.',
    tone: 'danger',
  },
};

// 입력과 결과는 이 화면의 상태에만 둔다. 응답은 원문 값을 포함하지 않으며, 화면도 결과에
// 입력을 복제하지 않는다. 다른 메뉴나 작업 화면으로 이동하면 둘 다 사라진다.
export function RiskPlayground({ features }: { features: readonly string[] }) {
  const { apiKey, rejectApiKey } = useChatSession();
  const checks = availableRiskChecks(features);
  const examples = availableRiskExamples(checks);
  const [checkId, setCheckId] = useState<RiskCheckId>(checks[0]?.id ?? 'pii');
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RiskRun | null>(null);
  const [failure, setFailure] = useState<{ message: string; requestId: string | null } | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const check = checks.find((item) => item.id === checkId) ?? checks[0] ?? null;
  const length = riskPromptLength(prompt);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (check === null || busy) return;
    const { body, error } = buildRiskRequest(prompt);
    setInputError(error);
    if (body === null) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const { payload, requestId } = await postPublicJson(apiKey, check.path, body, controller.signal);
      const interpreted = interpretRiskAssessment(payload);
      if (interpreted.error !== null) {
        setRun(null);
        setFailure({ message: interpreted.error, requestId });
      } else {
        setRun({ checkLabel: check.label, interpretation: interpreted.result, payload, requestId });
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 401) rejectApiKey();
      setRun(null);
      setFailure({
        message: apiErrorMessage(reason, 'Risk 요청에 실패했습니다.'),
        requestId: reason instanceof ApiError ? reason.requestId : null,
      });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  }

  if (check === null) {
    return <Alert isInline variant="warning" title="이 배포는 Risk 검사를 제공하지 않습니다." />;
  }

  const verdict = run ? VERDICT_TEXT[run.interpretation.verdict] : null;
  return (
    <section className="playground-workspace" aria-labelledby="risk-workspace-title">
      <div className="playground-panel-heading">
        <div>
          <h2 id="risk-workspace-title">Risk</h2>
          <p>텍스트의 PII·Secret{features.includes('prompt_detection') ? '·Prompt Injection' : ''} 위험 신호를 확인합니다. 결과는 신호이며 허용·차단 판정이 아닙니다.</p>
        </div>
      </div>

      <p className="playground-notice">
        실제 개인정보나 운영 Secret 대신 합성 예제를 사용하세요. 입력과 결과는 이 화면에만 있고 다른 화면으로
        이동하면 지워집니다. 요청 본문 로깅(<code>LOG_REQUEST_RESPONSE_BODY</code>)이 켜진 배포에서는 마스킹된
        입력 미리보기가 Gateway 로그에 남을 수 있습니다.
      </p>

      {examples.length > 0 ? (
        <div className="playground-example-strip" role="group" aria-label="합성 예제">
          {examples.map((example) => (
            <button
              key={example.id}
              type="button"
              className="playground-example-chip"
              disabled={busy}
              onClick={() => {
                setCheckId(example.check);
                setPrompt(example.prompt);
                setInputError(null);
              }}
            >
              <strong>{example.title}</strong>
              <span>{example.description}</span>
            </button>
          ))}
        </div>
      ) : null}

      <form className="playground-form" onSubmit={(event) => { void submit(event); }}>
        <fieldset className="playground-choice" disabled={busy}>
          <legend>검사 종류</legend>
          {checks.map((item) => (
            <label key={item.id}>
              <input type="radio" name="risk-check" checked={check.id === item.id} onChange={() => setCheckId(item.id)} />
              <span>{item.label}<small>{item.description}</small></span>
            </label>
          ))}
        </fieldset>
        <div className="playground-field">
          <label htmlFor="risk-input">검사할 텍스트</label>
          <textarea
            id="risk-input"
            rows={5}
            value={prompt}
            disabled={busy}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setPrompt(event.currentTarget.value)}
          />
          <small className={length > MAX_RISK_PROMPT_CHARACTERS ? 'form-error' : undefined}>
            {length.toLocaleString()} / {MAX_RISK_PROMPT_CHARACTERS.toLocaleString()}자
          </small>
        </div>
        <div className="chat-composer-actions">
          {inputError ? <p className="form-error" role="alert">{inputError}</p> : <span />}
          <div className="chat-heading-actions">
            <Button
              type="button"
              variant="secondary"
              isDisabled={busy || (!prompt && run === null)}
              onClick={() => {
                setPrompt('');
                setRun(null);
                setFailure(null);
                setInputError(null);
              }}
            >
              입력·결과 지우기
            </Button>
            <Button type="submit" variant="primary" isDisabled={busy}>{busy ? '검사 중…' : '검사'}</Button>
          </div>
        </div>
      </form>

      {failure ? (
        <Alert isInline variant="danger" title="Risk 요청이 완료되지 않았습니다.">
          <p>{failure.message}</p>
          {failure.requestId ? <p>Request ID: <code>{failure.requestId}</code></p> : null}
        </Alert>
      ) : null}

      {run && verdict ? (
        <section className="playground-result" aria-live="polite" aria-label="Risk 결과">
          <div className="playground-result-headline" data-tone={verdict.tone}>
            <span>{run.checkLabel}</span>
            <strong>{verdict.title}</strong>
            <small>{verdict.detail}</small>
          </div>
          <dl className="chat-facts">
            <div><dt>status</dt><dd>{run.interpretation.status}</dd></div>
            <div><dt>검사 완료</dt><dd>{run.interpretation.complete ? '예' : '아니요'}</dd></div>
            {run.interpretation.strongestCode ? (
              <div><dt>가장 강한 신호</dt><dd>{run.interpretation.strongestCode} · {riskCodeLabel(run.interpretation.strongestCode)}</dd></div>
            ) : null}
            {run.requestId ? <div><dt>Request ID</dt><dd><code>{run.requestId}</code></dd></div> : null}
          </dl>
          {run.interpretation.signals.length > 0 ? (
            <div className="table-scroll">
              <table className="playground-signal-table">
                <caption>탐지된 신호 · 원문 값은 응답에 포함되지 않습니다.</caption>
                <thead>
                  <tr><th scope="col">코드</th><th scope="col">유형</th><th scope="col">항목</th><th scope="col">개수</th><th scope="col">검사기</th></tr>
                </thead>
                <tbody>
                  {run.interpretation.signals.map((signal, index) => (
                    <tr key={`${signal.code}-${signal.label ?? ''}-${index}`}>
                      <td><code>{signal.code}</code></td>
                      <td>{riskCodeLabel(signal.code)}</td>
                      <td>{signal.label ?? '—'}</td>
                      <td>{signal.spanCount ?? '—'}</td>
                      <td>{signal.source ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {run.interpretation.systemSignals.length > 0 ? (
            <ul className="playground-system-signals">
              {run.interpretation.systemSignals.map((signal, index) => (
                <li key={`${signal.code}-${index}`}>
                  <code>{signal.code}</code> {systemSignalLabel(signal.code)}{signal.retryable ? ' · 재시도 가능' : ''}
                </li>
              ))}
            </ul>
          ) : null}
          <details className="playground-raw">
            <summary>원본 응답 JSON 보기</summary>
            <pre>{JSON.stringify(run.payload, null, 2)}</pre>
          </details>
        </section>
      ) : null}
    </section>
  );
}
