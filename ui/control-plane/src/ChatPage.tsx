import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';

import { fetchPublicModels } from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { requestLogDiagnosticsUrl } from './activityDiagnostics';
import { useChatSession } from './ChatSessionContext';
import {
  chatCapableModels,
  chatControls,
  turnFacts,
  turnNotice,
  type Exchange,
  type NumberControl,
  type PublicModel,
} from './chatSession';

type ChatPageProps = {
  grafanaUrl: string | null;
};

function rangeHint(control: NumberControl): string {
  return control.max === null ? `${control.min} 이상` : `${control.min}–${control.max}`;
}

function ApiKeyForm({ rejected }: { rejected: boolean }) {
  const { setApiKey } = useChatSession();
  const [draft, setDraft] = useState('');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = draft.trim();
    if (!key) return;
    setApiKey(key);
    setDraft('');
  }

  return (
    <Card className="chat-key-card">
      <CardTitle>API 키 필요</CardTitle>
      <CardBody>
        <p>
          이 Gateway의 공개 API는 Bearer 인증을 요구합니다. 관리자 키가 아니라 API 사용자에게 발급한
          키를 입력하세요. 키는 이 탭의 메모리에만 있고 새로고침하면 사라집니다.
        </p>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="chat-api-key">API 키</label>
          <input
            id="chat-api-key"
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
          />
          {rejected ? <p className="form-error" role="alert">API 키가 유효하지 않습니다.</p> : null}
          <Button type="submit" variant="primary" isDisabled={!draft.trim()}>사용</Button>
        </form>
      </CardBody>
    </Card>
  );
}

function ExchangeView({ exchange, grafanaUrl }: { exchange: Exchange; grafanaUrl: string | null }) {
  const turn = exchange.assistant;
  const streaming = turn.status === 'streaming';
  const facts = turnFacts(turn);
  const notice = turnNotice(turn);
  const logUrl = turn.requestId
    ? requestLogDiagnosticsUrl(grafanaUrl, turn.requestId, exchange.sentAtSeconds)
    : null;

  return (
    <li className="chat-exchange">
      <div className="chat-message chat-message-user">
        <span className="chat-role">나</span>
        <div className="chat-text">{exchange.user}</div>
      </div>
      <div className="chat-message chat-message-assistant" aria-busy={streaming}>
        <span className="chat-role">모델</span>
        {turn.reasoning ? (
          <details className="chat-reasoning">
            <summary>
              생각 과정 · {turn.reasoning.length.toLocaleString('ko-KR')}자
              {streaming && !turn.content ? ' (생성 중)' : ''}
            </summary>
            <div className="chat-text">{turn.reasoning}</div>
          </details>
        ) : null}
        {turn.content ? (
          <div className="chat-text">
            {turn.content}
            {streaming ? <span className="chat-cursor" aria-hidden="true">▍</span> : null}
          </div>
        ) : streaming && !turn.reasoning ? (
          <div className="chat-waiting"><Spinner size="sm" aria-label="응답 대기 중" /> 응답 대기 중…</div>
        ) : null}
        {turn.error ? (
          <Alert isInline isPlain variant="danger" title={turn.error.code ? `${turn.error.code}: ${turn.error.message}` : turn.error.message} />
        ) : null}
        {notice ? <p className="chat-notice">{notice}</p> : null}
        {facts.length > 0 || turn.requestId ? (
          <dl className="chat-facts">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
            {turn.requestId ? (
              <div>
                <dt>request_id</dt>
                <dd>
                  <code>{turn.requestId}</code>
                  {logUrl ? <a href={logUrl} target="_blank" rel="noreferrer">로그 ↗</a> : null}
                </dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </div>
    </li>
  );
}

function ChatSettingsPanel({ model }: { model: PublicModel }) {
  const { settings, updateSettings } = useChatSession();
  const controls = chatControls(model);
  const [open, setOpen] = useState(() => window.matchMedia?.('(min-width: 981px)').matches ?? true);
  const reasoningDefault = controls.reasoning?.defaultEnabled ?? false;
  const reasoningEnabled = settings.reasoning ?? reasoningDefault;

  return (
    <details className="chat-settings" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>요청 설정</summary>
      <div className="chat-settings-body">
        <label htmlFor="chat-system-prompt">시스템 프롬프트</label>
        <textarea
          id="chat-system-prompt"
          rows={4}
          value={settings.systemPrompt}
          placeholder="비워 두면 보내지 않습니다."
          onChange={(event) => updateSettings({ systemPrompt: event.currentTarget.value })}
        />
        {controls.temperature ? (
          <>
            <label htmlFor="chat-temperature">온도</label>
            <input
              id="chat-temperature"
              type="number"
              inputMode="decimal"
              step="0.1"
              min={controls.temperature.min}
              max={controls.temperature.max ?? undefined}
              placeholder="모델 기본값"
              value={settings.temperature}
              onChange={(event) => updateSettings({ temperature: event.currentTarget.value })}
            />
            <small>비우면 모델 기본값 · 허용 {rangeHint(controls.temperature)}</small>
          </>
        ) : null}
        {controls.maxTokens ? (
          <>
            <label htmlFor="chat-max-tokens">최대 출력 토큰</label>
            <input
              id="chat-max-tokens"
              type="number"
              inputMode="numeric"
              step="1"
              min={controls.maxTokens.min}
              max={controls.maxTokens.max ?? undefined}
              placeholder="모델 기본값"
              value={settings.maxTokens}
              onChange={(event) => updateSettings({ maxTokens: event.currentTarget.value })}
            />
            <small>비우면 모델 기본값 · 허용 {rangeHint(controls.maxTokens)}</small>
          </>
        ) : null}
        {controls.reasoning ? (
          <label className="chat-toggle">
            <input
              type="checkbox"
              checked={reasoningEnabled}
              onChange={(event) => updateSettings({ reasoning: event.currentTarget.checked })}
            />
            추론(생각 과정) 사용
            <small>모델 기본값: {reasoningDefault ? '켬' : '끔'}</small>
          </label>
        ) : null}
        {!controls.stream ? (
          <small>이 모델은 스트리밍을 광고하지 않아 응답을 한 번에 받습니다.</small>
        ) : null}
      </div>
    </details>
  );
}

export function ChatPage({ grafanaUrl }: ChatPageProps) {
  const session = useChatSession();
  const { apiKey, apiKeyRejected, exchanges, busy, send, stop, clear, setApiKey } = session;
  const [draft, setDraft] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const followRef = useRef(true);

  const modelsQuery = useQuery({
    queryKey: ['public-models', apiKey],
    queryFn: () => fetchPublicModels(apiKey),
    retry: false,
    staleTime: 30_000,
    // API 키를 바꿔 다시 불러오는 동안 대화 화면이 사라지지 않게 이전 목록을 유지한다.
    placeholderData: (previous) => previous,
  });
  const models = useMemo(
    () => chatCapableModels((modelsQuery.data?.data ?? []) as PublicModel[]),
    [modelsQuery.data],
  );
  const model = models.find((item) => item.id === selectedId) ?? models[0] ?? null;
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;

  // 사용자가 위로 스크롤해 이전 응답을 읽는 중이면 새 token이 와도 끌어내리지 않는다.
  useEffect(() => {
    const onScroll = () => {
      const root = document.documentElement;
      followRef.current = root.scrollHeight - (window.scrollY + window.innerHeight) < 160;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  // 입력창은 화면 아래에 붙어 있다. 문서 끝까지 내려야 마지막 응답이 입력창에 가리지 않는다.
  useEffect(() => {
    if (followRef.current) window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [exchanges]);

  function submit() {
    const text = draft.trim();
    if (!text || model === null) return;
    const error = send(model, text);
    setInputError(error);
    if (error === null) {
      setDraft('');
      followRef.current = true;
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중 Enter는 글자 확정이다. 보내면 마지막 글자가 잘린다.
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!busy) submit();
  }

  return (
    <section className="chat-page">
      <div className="page-heading">
        <div>
          <h1>채팅 테스트</h1>
          <p>
            공개 API(<code>/v1/chat/completions</code>)를 이 화면에서 직접 호출합니다. 대화는 이 탭의
            메모리에만 있고 서버에 저장하지 않습니다.
          </p>
        </div>
        <div className="chat-heading-actions">
          {apiKey !== null ? <Button variant="secondary" onClick={() => setApiKey(null)}>API 키 지우기</Button> : null}
          {exchanges.length > 0 ? <Button variant="secondary" onClick={clear}>대화 지우기</Button> : null}
        </div>
      </div>

      {needsKey ? <ApiKeyForm rejected={apiKey !== null} /> : null}

      {modelsQuery.isPending ? (
        <div className="inline-loading"><Spinner size="md" aria-label="모델 목록 불러오는 중" /> 모델 목록을 불러오는 중…</div>
      ) : null}
      {modelsQuery.isError && !needsKey ? (
        <Alert isInline variant="danger" title="모델 목록을 불러오지 못했습니다.">
          {apiErrorMessage(modelsQuery.error)}
        </Alert>
      ) : null}
      {modelsQuery.isSuccess && model === null ? (
        <Alert isInline variant="warning" title="채팅을 지원하는 공개 모델이 없습니다." />
      ) : null}

      {model !== null ? (
        <div className="chat-layout">
          <div className="chat-main">
            {exchanges.length === 0 ? (
              <p className="chat-empty">
                메시지를 보내면 <strong>{model.id}</strong>의 응답과 함께 첫 토큰 시간, 토큰 수,
                request_id가 표시됩니다.
              </p>
            ) : (
              <ol className="chat-log" aria-live="polite">
                {exchanges.map((exchange) => (
                  <ExchangeView key={exchange.id} exchange={exchange} grafanaUrl={grafanaUrl} />
                ))}
              </ol>
            )}
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                if (busy) stop();
                else submit();
              }}
            >
              <textarea
                id="chat-input"
                aria-label="메시지"
                rows={3}
                value={draft}
                placeholder="메시지 입력 · Enter 보내기 · Shift+Enter 줄바꿈"
                onChange={(event) => setDraft(event.currentTarget.value)}
                onKeyDown={onKeyDown}
              />
              <div className="chat-composer-actions">
                {inputError ? <p className="form-error" role="alert">{inputError}</p> : <span />}
                {busy ? (
                  <Button type="submit" variant="danger">중지</Button>
                ) : (
                  <Button type="submit" variant="primary" isDisabled={!draft.trim()}>보내기</Button>
                )}
              </div>
            </form>
          </div>
          <aside className="chat-side">
            {models.length > 1 ? (
              <div className="chat-model-select">
                <label htmlFor="chat-model">모델</label>
                <select
                  id="chat-model"
                  value={model.id}
                  onChange={(event) => {
                    setSelectedId(event.currentTarget.value);
                    // 추론 기본값은 모델마다 다르다. 이전 모델에서 고른 값을 끌고 가지 않는다.
                    session.updateSettings({ reasoning: null });
                  }}
                  disabled={busy}
                >
                  {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
                </select>
              </div>
            ) : (
              <p className="chat-model-name">모델 <strong>{model.id}</strong></p>
            )}
            <ChatSettingsPanel model={model} />
          </aside>
        </div>
      ) : null}
    </section>
  );
}
