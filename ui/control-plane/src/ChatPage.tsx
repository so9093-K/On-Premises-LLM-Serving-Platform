import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';

import { fetchPublicModels } from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { requestLogDiagnosticsUrl } from './activityDiagnostics';
import { useChatSession } from './ChatSessionContext';
import {
  attachmentAccept,
  chatCapableModels,
  chatControls,
  classifyAttachment,
  conversationAttachments,
  inputModalityLabel,
  modelFeatureLabels,
  normalizeChatSettingsForModel,
  numberControlRangeHint,
  pendingToolCallExchange,
  TOOL_CHOICE_DEFAULT,
  TOOL_CHOICE_NAMED,
  validateChatAttachments,
  turnFacts,
  turnNotice,
  type ChatAttachment,
  type ChatToolCall,
  type ChatToolResult,
  type Exchange,
  type NumberControl,
  type PublicModel,
} from './chatSession';

type ChatPageProps = {
  grafanaUrl: string | null;
};

type NumericSettingKey =
  | 'temperature'
  | 'maxTokens'
  | 'topP'
  | 'topK'
  | 'minP'
  | 'presencePenalty'
  | 'frequencyPenalty'
  | 'repetitionPenalty'
  | 'seed'
  | 'topLogprobs';

function NumericSetting({
  id,
  label,
  control,
  value,
  onChange,
}: {
  id: string;
  label: string;
  control: NumberControl;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="chat-setting-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        inputMode={control.integer ? 'numeric' : 'decimal'}
        step={control.integer ? 1 : 'any'}
        min={control.minimum && !control.minimum.exclusive ? control.minimum.value : undefined}
        max={control.maximum && !control.maximum.exclusive ? control.maximum.value : undefined}
        placeholder="모델 기본값"
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <small>비우면 모델 기본값 · 허용 {numberControlRangeHint(control)}</small>
    </div>
  );
}

function OptionalBooleanSetting({
  id,
  label,
  value,
  defaultEnabled,
  onChange,
}: {
  id: string;
  label: string;
  value: boolean | null;
  defaultEnabled: boolean | null;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <div className="chat-setting-field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value === null ? 'default' : value ? 'true' : 'false'}
        onChange={(event) => {
          const selected = event.currentTarget.value;
          onChange(selected === 'default' ? null : selected === 'true');
        }}
      >
        <option value="default">모델 기본값{defaultEnabled === null ? '' : ` · ${defaultEnabled ? '켬' : '끔'}`}</option>
        <option value="true">켬</option>
        <option value="false">끔</option>
      </select>
    </div>
  );
}

function formatFileBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function readFileDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('파일을 base64로 변환하지 못했습니다.'));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

async function chatAttachmentFromFile(
  file: File,
  model: PublicModel,
  existing: readonly ChatAttachment[],
): Promise<{ attachment: ChatAttachment | null; error: string | null }> {
  const classified = classifyAttachment(model, {
    name: file.name,
    mimeType: file.type,
    sizeBytes: file.size,
  });
  if (!('modality' in classified)) return { attachment: null, error: classified.error };

  const dataUrl = await readFileDataUrl(file);
  const comma = dataUrl.indexOf(',');
  if (comma < 0) return { attachment: null, error: '파일을 data URL로 변환하지 못했습니다.' };
  const attachment: ChatAttachment = {
    id: crypto.randomUUID(),
    name: file.name,
    modality: classified.modality,
    mimeType: file.type.toLowerCase(),
    sizeBytes: file.size,
    data: classified.modality === 'audio' ? dataUrl.slice(comma + 1) : dataUrl,
    ...(classified.audioFormat ? { audioFormat: classified.audioFormat } : {}),
  };
  const error = validateChatAttachments(model, [...existing, attachment]);
  return error ? { attachment: null, error } : { attachment, error: null };
}

function AttachmentList({
  attachments,
  removable = false,
  onRemove,
}: {
  attachments: readonly ChatAttachment[];
  removable?: boolean;
  onRemove?: (id: string) => void;
}) {
  if (attachments.length === 0) return null;
  return (
    <ul className="chat-attachment-list" aria-label="첨부 파일">
      {attachments.map((attachment) => (
        <li key={attachment.id}>
          <span>
            <strong>{inputModalityLabel(attachment.modality)}</strong>
            {' · '}
            {attachment.name}
            {' · '}
            {formatFileBytes(attachment.sizeBytes)}
          </span>
          {removable && onRemove ? (
            <button type="button" onClick={() => onRemove(attachment.id)} aria-label={`${attachment.name} 첨부 제거`}>
              제거
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ModelContext({ model }: { model: PublicModel }) {
  const features = modelFeatureLabels(model);
  return (
    <div className="chat-model-context">
      <span className="chat-model-context-label">현재 모델 계약</span>
      <div className="chat-model-identity">
        <strong>{model.id}</strong>
        <code>{model.backend}</code>
      </div>
      {features.length > 0 ? (
        <div className="chat-feature-list" aria-label="지원 기능">
          {features.map((feature) => <span className="chat-feature" key={feature}>{feature}</span>)}
        </div>
      ) : null}
    </div>
  );
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

function toolArgumentsAreJson(call: ChatToolCall): boolean {
  try {
    JSON.parse(call.function.arguments);
    return true;
  } catch {
    return false;
  }
}

function ToolResultForm({
  exchange,
  busy,
  onSend,
}: {
  exchange: Exchange;
  busy: boolean;
  onSend: (results: readonly ChatToolResult[]) => string | null;
}) {
  const calls = exchange.assistant.toolCalls;
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(calls.map((call) => [call.id, ''])),
  );
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const results = calls.map((call) => ({
      toolCallId: call.id,
      content: values[call.id] ?? '',
    }));
    const nextError = onSend(results);
    setError(nextError);
  }

  return (
    <form className="chat-tool-result-form" aria-label="도구 결과 입력" onSubmit={submit}>
      <strong>도구 결과 입력</strong>
      <small>Console은 함수를 실행하지 않습니다. 실제 실행 결과를 입력하면 같은 <code>tool_call_id</code>로 다음 요청을 보냅니다.</small>
      {calls.map((call, index) => (
        <div className="chat-setting-field" key={call.id}>
          <label htmlFor={`chat-tool-result-${exchange.id}-${call.id}`}>
            <code>{call.function.name}</code> 결과
          </label>
          <textarea
            id={`chat-tool-result-${exchange.id}-${call.id}`}
            rows={3}
            value={values[call.id] ?? ''}
            disabled={busy}
            autoFocus={index === 0}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setValues((current) => ({
                ...current,
                [call.id]: value,
              }));
            }}
          />
        </div>
      ))}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <Button type="submit" variant="secondary" isDisabled={busy}>
        도구 결과 보내기
      </Button>
    </form>
  );
}

function ExchangeView({
  exchange,
  grafanaUrl,
  pendingToolResult,
  busy,
  onSendToolResults,
}: {
  exchange: Exchange;
  grafanaUrl: string | null;
  pendingToolResult: boolean;
  busy: boolean;
  onSendToolResults: (sourceExchangeId: number, results: readonly ChatToolResult[]) => string | null;
}) {
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
        <span className="chat-role">{exchange.toolResults?.length ? '도구 결과' : '나'}</span>
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
        <span className="chat-role">모델</span>
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
          <div className="chat-text">
            {turn.content}
            {streaming ? <span className="chat-cursor" aria-hidden="true">▍</span> : null}
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
            onSend={(results) => onSendToolResults(exchange.id, results)}
          />
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
      </div>
    </li>
  );
}

function ChatSettingsPanel({ model }: { model: PublicModel }) {
  const { settings, updateSettings } = useChatSession();
  const controls = chatControls(model);
  const [open, setOpen] = useState(() => window.matchMedia?.('(min-width: 981px)').matches ?? true);
  const logprobsDefault = controls.logprobs?.defaultEnabled ?? false;
  const logprobsEnabled = settings.logprobs ?? logprobsDefault;

  const advancedNumeric: Array<{
    key: NumericSettingKey;
    id: string;
    label: string;
    control: NumberControl | null;
  }> = [
    { key: 'temperature', id: 'chat-temperature', label: '온도', control: controls.temperature },
    { key: 'topP', id: 'chat-top-p', label: 'Top P', control: controls.topP },
    { key: 'topK', id: 'chat-top-k', label: 'Top K', control: controls.topK },
    { key: 'minP', id: 'chat-min-p', label: 'Min P', control: controls.minP },
    { key: 'presencePenalty', id: 'chat-presence-penalty', label: '존재 페널티', control: controls.presencePenalty },
    { key: 'frequencyPenalty', id: 'chat-frequency-penalty', label: '빈도 페널티', control: controls.frequencyPenalty },
    { key: 'repetitionPenalty', id: 'chat-repetition-penalty', label: '반복 페널티', control: controls.repetitionPenalty },
    { key: 'seed', id: 'chat-seed', label: 'Seed', control: controls.seed },
  ];

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

        {controls.maxTokens ? (
          <NumericSetting
            id="chat-max-tokens"
            label="최대 출력 토큰"
            control={controls.maxTokens}
            value={settings.maxTokens}
            onChange={(value) => updateSettings({ maxTokens: value })}
          />
        ) : null}

        {controls.reasoning ? (
          <OptionalBooleanSetting
            id="chat-reasoning"
            label="추론 출력"
            value={settings.reasoning}
            defaultEnabled={controls.reasoning.defaultEnabled}
            onChange={(value) => updateSettings({ reasoning: value })}
          />
        ) : null}

        {controls.stream ? (
          <label className="chat-toggle">
            <input
              type="checkbox"
              checked={controls.stream.constValue ?? settings.stream}
              disabled={controls.stream.constValue !== null}
              onChange={(event) => updateSettings({ stream: event.currentTarget.checked })}
            />
            스트리밍 응답
            <small>
              {controls.stream.constValue !== null
                ? `현재 모델 정책에서 ${controls.stream.constValue ? '켬' : '끔'}으로 고정`
                : '끄면 응답을 한 번에 받습니다.'}
            </small>
          </label>
        ) : (
          <small>이 모델은 스트리밍을 광고하지 않아 응답을 한 번에 받습니다.</small>
        )}

        <details className="chat-advanced-settings">
          <summary>고급 생성 설정</summary>
          <div className="chat-advanced-settings-body">
            {advancedNumeric.map((item) => item.control ? (
              <NumericSetting
                key={item.key}
                id={item.id}
                label={item.label}
                control={item.control}
                value={settings[item.key]}
                onChange={(value) => updateSettings({ [item.key]: value })}
              />
            ) : null)}

            {controls.stop ? (
              <div className="chat-setting-field">
                <label htmlFor="chat-stop">중지 문자열</label>
                <textarea
                  id="chat-stop"
                  rows={3}
                  value={settings.stop}
                  placeholder="한 줄에 하나씩 입력 · 비우면 보내지 않음"
                  onChange={(event) => updateSettings({ stop: event.currentTarget.value })}
                />
                <small>
                  응답 생성을 멈출 문자열
                  {controls.stop.maxItems === null ? '' : ` · 최대 ${controls.stop.maxItems}개`}
                </small>
              </div>
            ) : null}

            {controls.logprobs ? (
              <OptionalBooleanSetting
                id="chat-logprobs"
                label="로그확률"
                value={settings.logprobs}
                defaultEnabled={controls.logprobs.defaultEnabled}
                onChange={(value) => updateSettings({
                  logprobs: value,
                  ...(value === false ? { topLogprobs: '' } : {}),
                })}
              />
            ) : null}

            {controls.topLogprobs ? (
              <fieldset className="chat-setting-group" disabled={!logprobsEnabled}>
                <NumericSetting
                  id="chat-top-logprobs"
                  label="Top logprobs"
                  control={controls.topLogprobs}
                  value={settings.topLogprobs}
                  onChange={(value) => updateSettings({ topLogprobs: value })}
                />
                {!logprobsEnabled ? <small>로그확률을 켜야 사용할 수 있습니다.</small> : null}
              </fieldset>
            ) : null}

            {controls.logprobs && logprobsEnabled && settings.stream && controls.logprobs.allowStream === false ? (
              <small className="form-error">현재 모델은 스트리밍 응답에서 로그확률을 지원하지 않습니다.</small>
            ) : null}

            {controls.fixedN !== null ? (
              <small>응답 개수 <code>n</code>은 현재 모델 정책에서 {controls.fixedN}개로 고정됩니다.</small>
            ) : null}
          </div>
        </details>

        {controls.tools ? (
          <details className="chat-tool-settings">
            <summary>도구 호출</summary>
            <div className="chat-tool-settings-body">
              <small>
                Console은 도구를 실행하지 않고 request/response round trip만 검증합니다.
                {controls.tools.minItems !== null ? ` · tools 사용 시 최소 ${controls.tools.minItems}개` : ''}
                {controls.tools.maxItems !== null ? ` · 최대 ${controls.tools.maxItems}개` : ''}
              </small>

              {settings.toolDrafts.map((tool, index) => (
                <fieldset className="chat-tool-definition" key={tool.id}>
                  <legend>Function {index + 1}</legend>
                  <div className="chat-setting-field">
                    <label htmlFor={`chat-tool-name-${tool.id}`}>Function 이름</label>
                    <input
                      id={`chat-tool-name-${tool.id}`}
                      type="text"
                      value={tool.name}
                      onChange={(event) => updateSettings({
                        toolDrafts: settings.toolDrafts.map((item) => (
                          item.id === tool.id ? { ...item, name: event.currentTarget.value } : item
                        )),
                      })}
                    />
                  </div>
                  <div className="chat-setting-field">
                    <label htmlFor={`chat-tool-description-${tool.id}`}>설명</label>
                    <input
                      id={`chat-tool-description-${tool.id}`}
                      type="text"
                      value={tool.description}
                      onChange={(event) => updateSettings({
                        toolDrafts: settings.toolDrafts.map((item) => (
                          item.id === tool.id ? { ...item, description: event.currentTarget.value } : item
                        )),
                      })}
                    />
                  </div>
                  <div className="chat-setting-field">
                    <label htmlFor={`chat-tool-parameters-${tool.id}`}>Parameters JSON Schema</label>
                    <textarea
                      id={`chat-tool-parameters-${tool.id}`}
                      rows={6}
                      spellCheck={false}
                      value={tool.parametersText}
                      onChange={(event) => updateSettings({
                        toolDrafts: settings.toolDrafts.map((item) => (
                          item.id === tool.id ? { ...item, parametersText: event.currentTarget.value } : item
                        )),
                      })}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="link"
                    onClick={() => {
                      const next = settings.toolDrafts.filter((item) => item.id !== tool.id);
                      updateSettings({
                        toolDrafts: next,
                        ...(settings.toolChoice === TOOL_CHOICE_NAMED && settings.toolChoiceName === tool.name.trim()
                          ? { toolChoiceName: '' }
                          : {}),
                      });
                    }}
                  >
                    Function 제거
                  </Button>
                </fieldset>
              ))}

              <Button
                type="button"
                variant="secondary"
                isDisabled={controls.tools.maxItems !== null && settings.toolDrafts.length >= controls.tools.maxItems}
                onClick={() => updateSettings({
                  toolDrafts: [
                    ...settings.toolDrafts,
                    {
                      id: crypto.randomUUID(),
                      name: '',
                      description: '',
                      parametersText: '{}',
                      strict: null,
                    },
                  ],
                })}
              >
                Function 추가
              </Button>

              {(controls.tools.choiceAllowed.length > 0 || controls.tools.allowNamed) ? (
                <div className="chat-setting-field">
                  <label htmlFor="chat-tool-choice">Tool choice</label>
                  <select
                    id="chat-tool-choice"
                    value={settings.toolChoice}
                    onChange={(event) => updateSettings({
                      toolChoice: event.currentTarget.value,
                      toolChoiceName: '',
                    })}
                  >
                    <option value={TOOL_CHOICE_DEFAULT}>모델 기본값</option>
                    {controls.tools.choiceAllowed.map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                    {controls.tools.allowNamed ? <option value={TOOL_CHOICE_NAMED}>특정 function</option> : null}
                  </select>
                </div>
              ) : null}

              {settings.toolChoice === TOOL_CHOICE_NAMED && controls.tools.allowNamed ? (
                <div className="chat-setting-field">
                  <label htmlFor="chat-tool-choice-name">Function 선택</label>
                  <select
                    id="chat-tool-choice-name"
                    value={settings.toolChoiceName}
                    onChange={(event) => updateSettings({ toolChoiceName: event.currentTarget.value })}
                  >
                    <option value="">선택하세요</option>
                    {settings.toolDrafts
                      .map((tool) => tool.name.trim())
                      .filter((name, index, names) => name && names.indexOf(name) === index)
                      .map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </div>
              ) : null}

              {controls.tools.parallelConst !== null ? (
                <small>
                  병렬 도구 호출은 현재 모델 정책에서 {controls.tools.parallelConst ? '허용' : '비활성'} 상태입니다.
                </small>
              ) : null}
            </div>
          </details>
        ) : null}

        {controls.responseFormat ? (
          <details className="chat-output-settings">
            <summary>응답 형식</summary>
            <div className="chat-output-settings-body">
              <div className="chat-setting-field">
                <label htmlFor="chat-response-format">출력 형식</label>
                <select
                  id="chat-response-format"
                  value={settings.responseFormat}
                  onChange={(event) => updateSettings({
                    responseFormat: event.currentTarget.value as typeof settings.responseFormat,
                  })}
                >
                  <option value="default">모델 기본값</option>
                  {controls.responseFormat.allowedTypes.map((value) => (
                    <option key={value} value={value}>
                      {value === 'text' ? 'Text' : value === 'json_object' ? 'JSON object' : value === 'json_schema' ? 'JSON Schema' : value}
                    </option>
                  ))}
                </select>
              </div>

              {settings.responseFormat === 'json_object' && controls.responseFormat.requireJsonInstruction ? (
                <small>JSON object 모드는 시스템 프롬프트나 메시지에 JSON으로 답하라는 지시가 있어야 합니다.</small>
              ) : null}

              {settings.responseFormat === 'json_schema' && controls.responseFormat.jsonSchema ? (
                <>
                  <div className="chat-setting-field">
                    <label htmlFor="chat-json-schema-name">Schema 이름</label>
                    <input
                      id="chat-json-schema-name"
                      type="text"
                      value={settings.jsonSchemaName}
                      onChange={(event) => updateSettings({ jsonSchemaName: event.currentTarget.value })}
                    />
                    <small>이름의 최종 형식 검증은 Gateway 계약이 수행합니다.</small>
                  </div>
                  {controls.responseFormat.jsonSchema.strictRequireTrue ? (
                    <label className="chat-toggle">
                      <input type="checkbox" checked disabled />
                      Strict schema
                      <small>현재 모델 정책에서 true로 고정</small>
                    </label>
                  ) : controls.responseFormat.jsonSchema.strictAllowed ? (
                    <OptionalBooleanSetting
                      id="chat-json-schema-strict"
                      label="Strict schema"
                      value={settings.jsonSchemaStrict}
                      defaultEnabled={null}
                      onChange={(value) => updateSettings({ jsonSchemaStrict: value })}
                    />
                  ) : null}
                  <div className="chat-setting-field">
                    <label htmlFor="chat-json-schema">JSON Schema</label>
                    <textarea
                      id="chat-json-schema"
                      rows={10}
                      spellCheck={false}
                      value={settings.jsonSchemaText}
                      placeholder='{"type":"object","properties":{},"required":[],"additionalProperties":false}'
                      onChange={(event) => updateSettings({ jsonSchemaText: event.currentTarget.value })}
                    />
                    <small>
                      {[
                        controls.responseFormat.jsonSchema.maxSchemaBytes !== null
                          ? `최대 ${controls.responseFormat.jsonSchema.maxSchemaBytes.toLocaleString('ko-KR')} bytes`
                          : null,
                        controls.responseFormat.jsonSchema.maxDepth !== null
                          ? `depth ${controls.responseFormat.jsonSchema.maxDepth}`
                          : null,
                        controls.responseFormat.jsonSchema.maxTotalProperties !== null
                          ? `properties ${controls.responseFormat.jsonSchema.maxTotalProperties}개`
                          : null,
                      ].filter(Boolean).join(' · ')}
                    </small>
                  </div>
                </>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
    </details>
  );
}

export function ChatPage({ grafanaUrl }: ChatPageProps) {
  const session = useChatSession();
  const { apiKey, apiKeyRejected, exchanges, busy, send, sendToolResults, stop, clear, setApiKey } = session;
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
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
  const pendingToolExchange = pendingToolCallExchange(exchanges);

  useEffect(() => {
    if (model === null) return;
    const normalized = normalizeChatSettingsForModel(session.settings, model);
    if (normalized !== session.settings) session.updateSettings(normalized);
  }, [model, session.settings, session.updateSettings]);

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

  async function onAttachmentsSelected(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = '';
    if (model === null || files.length === 0) return;
    setAttachmentBusy(true);
    setInputError(null);
    try {
      let next = [...attachments];
      const history = conversationAttachments(exchanges);
      for (const file of files) {
        const result = await chatAttachmentFromFile(file, model, [...history, ...next]);
        if (result.error) {
          setInputError(result.error);
          break;
        }
        if (result.attachment) next = [...next, result.attachment];
      }
      setAttachments(next);
    } catch (reason) {
      setInputError(reason instanceof Error ? reason.message : '첨부 파일을 읽지 못했습니다.');
    } finally {
      setAttachmentBusy(false);
    }
  }

  function submit() {
    const text = draft.trim();
    if ((!text && attachments.length === 0) || model === null) return;
    const error = send(model, text, attachments);
    setInputError(error);
    if (error === null) {
      setDraft('');
      setAttachments([]);
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
              <ol className="chat-log" aria-live="polite" aria-atomic="false" aria-relevant="additions text">
                {exchanges.map((exchange) => (
                  <ExchangeView
                    key={exchange.id}
                    exchange={exchange}
                    grafanaUrl={grafanaUrl}
                    pendingToolResult={pendingToolExchange?.id === exchange.id}
                    busy={busy}
                    onSendToolResults={(sourceExchangeId, results) => sendToolResults(model, sourceExchangeId, results)}
                  />
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
              <AttachmentList
                attachments={attachments}
                removable
                onRemove={(id) => setAttachments((items) => items.filter((item) => item.id !== id))}
              />
              {pendingToolExchange ? (
                <p className="chat-notice">모델이 도구 결과를 기다리고 있습니다. 위 tool call에 결과를 입력한 뒤 계속하세요.</p>
              ) : null}
              <textarea
                id="chat-input"
                aria-label="메시지"
                rows={3}
                value={draft}
                disabled={pendingToolExchange !== null}
                placeholder={pendingToolExchange
                  ? '도구 결과를 먼저 입력하세요.'
                  : '메시지 입력 · Enter 보내기 · Shift+Enter 줄바꿈'}
                onChange={(event) => setDraft(event.currentTarget.value)}
                onKeyDown={onKeyDown}
              />
              <div className="chat-composer-tools">
                {attachmentAccept(model) ? (
                  <div className="chat-attachment-input">
                    <label htmlFor="chat-attachments">파일 첨부</label>
                    <input
                      id="chat-attachments"
                      type="file"
                      multiple
                      accept={attachmentAccept(model)}
                      disabled={busy || attachmentBusy || pendingToolExchange !== null}
                      onChange={(event) => { void onAttachmentsSelected(event); }}
                    />
                  </div>
                ) : <small>현재 모델은 파일 입력을 광고하지 않습니다.</small>}
              </div>
              <div className="chat-composer-actions">
                {inputError ? <p className="form-error" role="alert">{inputError}</p> : attachmentBusy ? <span>첨부 파일 읽는 중…</span> : <span />}
                {busy ? (
                  <Button type="submit" variant="danger">중지</Button>
                ) : (
                  <Button
                    type="submit"
                    variant="primary"
                    isDisabled={pendingToolExchange !== null || attachmentBusy || (!draft.trim() && attachments.length === 0)}
                  >
                    보내기
                  </Button>
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
                    setAttachments([]);
                    // 추론 기본값은 모델마다 다르다. 이전 모델에서 고른 값을 끌고 가지 않는다.
                    session.updateSettings({
                      reasoning: null,
                      logprobs: null,
                      topLogprobs: '',
                      responseFormat: 'default',
                      jsonSchemaName: 'response',
                      jsonSchemaText: '',
                      jsonSchemaStrict: null,
                      toolDrafts: [],
                      toolChoice: TOOL_CHOICE_DEFAULT,
                      toolChoiceName: '',
                    });
                  }}
                  disabled={busy}
                >
                  {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
                </select>
              </div>
            ) : (
              <p className="chat-model-name">모델 <strong>{model.id}</strong></p>
            )}
            <ModelContext model={model} />
            <ChatSettingsPanel model={model} />
          </aside>
        </div>
      ) : null}
    </section>
  );
}
