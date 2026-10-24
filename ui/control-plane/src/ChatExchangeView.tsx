import { useState } from 'react';
import { Alert, Spinner } from '@patternfly/react-core';
import { ChatMarkdown } from './ChatMarkdown';
import { requestLogDiagnosticsUrl } from './activityDiagnostics';
import { AttachmentList } from './ChatAttachments';
import { ToolResultForm, toolArgumentsAreJson } from './ChatToolResultForm';
import { RequestExportPanel } from './RequestExportPanel';
import { inputModalityLabel, turnFacts, turnNotice, type ChatToolResult, type Exchange } from './chatSession';

export function ExchangeView({
  exchange,
  grafanaUrl,
  docsUrl,
  pendingToolResult,
  busy,
  toolSendDisabled,
  onSendToolResults,
}: {
  exchange: Exchange;
  grafanaUrl: string | null;
  docsUrl: string | null;
  pendingToolResult: boolean;
  busy: boolean;
  toolSendDisabled: boolean;
  onSendToolResults: (sourceExchangeId: number, results: readonly ChatToolResult[]) => string | null;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState('');
  const turn = exchange.assistant;
  const streaming = turn.status === 'streaming';
  const formatted = !streaming && !showRaw;
  const facts = turnFacts(turn);
  const notice = turnNotice(turn);
  const logUrl = turn.requestId
    ? requestLogDiagnosticsUrl(grafanaUrl, turn.requestId, exchange.sentAtSeconds)
    : null;

  async function copyResponse(): Promise<void> {
    try {
      await navigator.clipboard.writeText(turn.content);
      setCopyFeedback(turn.status === 'complete'
        ? '응답 원문을 복사했습니다.'
        : '완료되지 않은 응답의 원문을 복사했습니다.');
    } catch {
      setCopyFeedback('복사하지 못했습니다. 브라우저의 클립보드 권한과 HTTPS 연결을 확인하세요.');
    }
  }

  return (
    <li className="chat-exchange">
      <div className="chat-message chat-message-user">
        {/* 내 메시지는 말풍선 위치로 구분하고, 이름은 화면 낭독기에만 제공한다. */}
        <span className={`chat-role${exchange.toolResults?.length ? '' : ' sr-only'}`}>{exchange.toolResults?.length ? '도구 결과' : '나'}</span>
        {exchange.toolResults?.length ? (
          <ul className="chat-tool-result-list" aria-label="전송한 도구 결과">
            {exchange.toolResults.map((result) => (
              <li key={result.toolCallId}>
                <code>{result.toolCallId}</code>
                <pre>{result.content}</pre>
              </li>
            ))}
          </ul>
        ) : (
          <>
            {exchange.user ? <div className="chat-text">{exchange.user}</div> : null}
            <AttachmentList attachments={exchange.attachments} />
          </>
        )}
      </div>
      <div className="chat-message chat-message-assistant" aria-busy={streaming}>
        <span className="chat-role">모델 · {exchange.requestContext.modelId} · {exchange.requestContext.backend}</span>
        {turn.reasoning ? (
          <details className="chat-reasoning">
            <summary>
              추론 출력 · {turn.reasoning.length.toLocaleString('ko-KR')}자
              {streaming && !turn.content ? ' (생성 중)' : ''}
            </summary>
            <div className="chat-text">{turn.reasoning}</div>
          </details>
        ) : null}
        {turn.content ? (
          <div className="chat-response">
            <div className="chat-response-actions">
              {!streaming ? (
                <button type="button" onClick={() => setShowRaw((value) => !value)}>
                  {showRaw ? '서식 보기' : '원문 보기'}
                </button>
              ) : null}
              <button type="button" disabled={streaming} onClick={() => { void copyResponse(); }}>
                응답 복사
              </button>
            </div>
            {formatted
              ? <ChatMarkdown text={turn.content} />
              : <div className="chat-text chat-response-raw">{turn.content}</div>}
            {streaming ? <span className="chat-cursor" aria-hidden="true">▍</span> : null}
            <span className="chat-response-copy-status" role="status">{copyFeedback}</span>
          </div>
        ) : streaming && !turn.reasoning ? (
          <div className="chat-waiting"><Spinner size="sm" aria-label="응답 대기 중" /> 응답 대기 중…</div>
        ) : null}
        {turn.toolCalls.length > 0 ? (
          <div className="chat-tool-calls" role="group" aria-label="모델 도구 호출">
            {turn.toolCalls.map((call, index) => (
              <div className="chat-tool-call" key={call.id || `tool-call-${index}`}>
                <div>
                  <strong>{call.function.name || '함수 이름 수신 중…'}</strong>
                  {call.id ? <code>{call.id}</code> : null}
                </div>
                <pre>{call.function.arguments || 'arguments 수신 중…'}</pre>
                <small>
                  {call.function.arguments
                    ? toolArgumentsAreJson(call) ? 'arguments JSON 정상' : streaming ? 'arguments JSON 수신 중' : 'arguments JSON 파싱 실패'
                    : 'arguments 대기 중'}
                </small>
              </div>
            ))}
          </div>
        ) : null}
        {pendingToolResult ? (
          <ToolResultForm
            exchange={exchange}
            busy={busy}
            sendingDisabled={toolSendDisabled}
            onSend={(results) => onSendToolResults(exchange.id, results)}
          />
        ) : null}
        {turn.error ? (
          <Alert isInline isPlain variant="danger" title={turn.error.code ? `${turn.error.code}: ${turn.error.message}` : turn.error.message} />
        ) : null}
        {notice ? <p className="chat-notice">{notice}</p> : null}
      </div>
      {/* 지표·요청 재현 정보는 답변 말풍선 밖의 작은 메타 줄에 둔다. 답변 본문이 먼저 읽힌다. */}
      <div className="chat-turn-meta">
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
        <details className="chat-request-context">
          <summary>요청 정보</summary>
          <dl className="facts compact-facts">
            <dt>모델</dt><dd>{exchange.requestContext.modelId}</dd>
            <dt>Backend</dt><dd><code>{exchange.requestContext.backend}</code></dd>
            <dt>입력</dt>
            <dd>
              {exchange.requestContext.inputModalities.length > 0
                ? exchange.requestContext.inputModalities.map(inputModalityLabel).join(', ')
                : '—'}
            </dd>
            <dt>Capability</dt>
            <dd>{exchange.requestContext.capabilities.join(', ') || '—'}</dd>
            <dt>파라미터</dt>
            <dd><code>{JSON.stringify(exchange.requestContext.parameters)}</code></dd>
          </dl>
        </details>
        <RequestExportPanel receipt={exchange.receipt} status={turn.status} />
        {docsUrl && turn.status === 'complete' ? (
          <a href={docsUrl} target="_blank" rel="noreferrer">API 문서 ↗</a>
        ) : null}
      </div>
    </li>
  );
}

