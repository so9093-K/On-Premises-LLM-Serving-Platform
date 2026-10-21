import { modelRuntimeLabel } from './uiText';
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { Alert, Button, Spinner } from '@patternfly/react-core';
import { conversationEndNearViewport } from './chatScroll';

import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { useChatSession } from './ChatSessionContext';
import { chatAttachmentFromFile, AttachmentList } from './ChatAttachments';
import { ExchangeView } from './ChatExchangeView';
import { ChatSettingsPanel } from './ChatSettingsPanel';
import { PlaygroundExampleGallery } from './PlaygroundExampleGallery';
import { usePublicModels } from './publicModelsQuery';
import { exampleAttachmentSummary, exampleAvailability, exampleRequiresFreshConversation, exampleSettingsConflict, exampleSettingsPatch, EXAMPLE_SAMPLE_ASSETS, PLAYGROUND_EXAMPLES, type PlaygroundExample } from './playgroundExamples';
import chartSampleUrl from './playgroundAssets/sample-chart.png';
import orderSampleUrl from './playgroundAssets/sample-order.png';
import diagramSampleUrl from './playgroundAssets/sample-diagram.png';
import audioSampleUrl from './playgroundAssets/sample-audio.wav';
import videoSampleUrl from './playgroundAssets/sample-video.webm?no-inline';
import {
  attachmentAccept,
  buildChatRequest,
  chatCapableModels,
  DEFAULT_CHAT_SETTINGS,
  chatControls,
  conversationAttachments,
  modelFeatureLabels,
  normalizeChatSettingsForModel,
  pendingToolCallExchange,
  planModelSwitch,
  validateChatAttachments,
  type ChatAttachment,
  type PublicModel,
} from './chatSession';

const SAMPLE_URLS = { chart: chartSampleUrl, order: orderSampleUrl, diagram: diagramSampleUrl, audio: audioSampleUrl, video: videoSampleUrl };

type ChatPageProps = {
  grafanaUrl: string | null;
  docsUrl: string | null;
};

function ModelContext({ model, showIdentity }: { model: PublicModel; showIdentity: boolean }) {
  const features = modelFeatureLabels(model);
  return (
    <div className="chat-model-context">
      {showIdentity ? <strong>{model.id}</strong> : null}
      <span>{model.display_name ?? model.id} · {modelRuntimeLabel(model.backend)}</span>
      {model.upstream_model_id ? <small>{model.upstream_model_id}</small> : null}
      {model.context_window ? <small>문맥 {model.context_window.toLocaleString()} tokens · 최대 출력 {String(model.request_parameters.max_tokens?.max ?? '—')} tokens</small> : null}
      {features.length > 0 ? (
        <div className="chat-feature-list" aria-label="지원 기능">
          {features.map((feature) => <span className="chat-feature" key={feature}>{feature}</span>)}
        </div>
      ) : null}
    </div>
  );
}

export function ChatPage({ grafanaUrl, docsUrl }: ChatPageProps) {
  const session = useChatSession();
  const { apiKey, apiKeyRejected, exchanges, busy, send, sendToolResults, stop, clear } = session;
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showExamples, setShowExamples] = useState(() => exchanges.length === 0);
  const [selectedExampleId, setSelectedExampleId] = useState<string | null>(null);
  const [appliedExampleId, setAppliedExampleId] = useState<string | null>(null);
  const [pendingModelId, setPendingModelId] = useState<string | null>(null);
  const [confirmExampleReplace, setConfirmExampleReplace] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);
  const [exampleLoading, setExampleLoading] = useState(false);
  const [focusComposerAfterExample, setFocusComposerAfterExample] = useState(false);
  const applySequenceRef = useRef(0);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const followRef = useRef(true);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  const modelsQuery = usePublicModels(apiKey);
  const models = useMemo(
    () => chatCapableModels((modelsQuery.data?.data ?? []) as PublicModel[]),
    [modelsQuery.data],
  );
  const model = models.find((item) => item.id === selectedId) ?? models[0] ?? null;
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;
  const pendingToolExchange = pendingToolCallExchange(exchanges);
  const pendingModel = models.find((item) => item.id === pendingModelId) ?? null;
  const pendingSwitchPlan = pendingModel
    ? planModelSwitch(pendingModel, session.settings, exchanges, attachments, draft)
    : null;

  useEffect(() => {
    if (pendingModelId !== null && !models.some((item) => item.id === pendingModelId)) {
      setPendingModelId(null);
    }
  }, [pendingModelId, models]);
  const exampleSnapshotRef = useRef({ model, settings: session.settings, exchanges });
  exampleSnapshotRef.current = { model, settings: session.settings, exchanges };

  function cancelExamplePreparation() {
    applySequenceRef.current += 1;
    setExampleLoading(false);
    setConfirmExampleReplace(false);
  }

  // Revalidate after any runtime capability, configuration or conversation change.
  // In-flight sample reads must never overwrite newer settings or conversation state.
  useEffect(() => {
    cancelExamplePreparation();
    setExampleError(null);
  }, [model, session.settings, exchanges]);

  // A disabled textarea cannot receive focus. Focus after React has committed
  // the state change that makes the input editable again.
  useEffect(() => {
    if (!focusComposerAfterExample || exampleLoading || attachmentBusy || pendingToolExchange) return;
    composerRef.current?.focus();
    setFocusComposerAfterExample(false);
  }, [focusComposerAfterExample, exampleLoading, attachmentBusy, pendingToolExchange]);

  useEffect(() => {
    if (model === null) return;
    const normalized = normalizeChatSettingsForModel(session.settings, model);
    if (normalized !== session.settings) session.updateSettings(normalized);
  }, [model, session.settings, session.updateSettings]);

  // 모바일에서는 설정 패널이 채팅 뒤에 있으므로 문서의 맨 끝이 아닌 대화 끝만 추적한다.
  // 사용자가 과거 응답을 읽고 있으면 새 스트리밍 토큰이 스크롤 위치를 빼앗지 않는다.
  useEffect(() => {
    const onScroll = () => {
      const end = conversationEndRef.current;
      if (end) followRef.current = conversationEndNearViewport(end.getBoundingClientRect().top, window.innerHeight);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  useEffect(() => {
    if (followRef.current) conversationEndRef.current?.scrollIntoView({ block: 'end' });
  }, [exchanges]);

  async function onAttachmentsSelected(event: ChangeEvent<HTMLInputElement>) {
    if (pendingModelId !== null) return;
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = '';
    if (model === null || files.length === 0 || exampleLoading) return;
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

  function validateExampleRequest(example: PlaygroundExample): string | null {
    if (model === null) return '현재 모델을 선택할 수 없습니다.';
    const patch = exampleSettingsPatch(example, DEFAULT_CHAT_SETTINGS);
    return buildChatRequest(
      model,
      { ...DEFAULT_CHAT_SETTINGS, ...patch },
      [],
      example.prompt,
    ).error;
  }

  async function applyExample(example: PlaygroundExample) {
    if (model === null || busy || attachmentBusy || exampleLoading || pendingToolExchange || pendingModelId !== null) return;
    const support = exampleAvailability(example, model, chatControls(model), validateExampleRequest);
    if (!support.available) {
      setExampleError(support.reason);
      return;
    }
    if (exchanges.length > 0 && exampleRequiresFreshConversation(example)) {
      setExampleError('기존 대화를 지운 다음 이 예제를 적용하세요. 완료된 대화는 자동으로 삭제하지 않습니다.');
      return;
    }
    const patch = exampleSettingsPatch(example, DEFAULT_CHAT_SETTINGS);
    if (!confirmExampleReplace && (draft.trim() || attachments.length > 0
      || exampleSettingsConflict(session.settings, patch))) {
      setConfirmExampleReplace(true);
      return;
    }

    const sequence = ++applySequenceRef.current;
    const initialContext = exampleSnapshotRef.current;
    const contextUnchanged = () => (
      sequence === applySequenceRef.current
      && exampleSnapshotRef.current.model === initialContext.model
      && exampleSnapshotRef.current.settings === initialContext.settings
      && exampleSnapshotRef.current.exchanges === initialContext.exchanges
    );
    setExampleLoading(true);
    setExampleError(null);
    try {
      const sampleAttachments: ChatAttachment[] = [];
      if (example.sample) {
        const asset = EXAMPLE_SAMPLE_ASSETS[example.sample];
        const assetUrl = SAMPLE_URLS[example.sample];
        const response = await fetch(assetUrl, { credentials: 'same-origin' });
        if (!response.ok) throw new Error('예제 파일을 가져오지 못했습니다.');
        const blob = await response.blob();
        if (!contextUnchanged()) return;
        if (blob.size !== asset.bytes) throw new Error('예제 파일의 크기가 등록된 자산과 일치하지 않습니다.');
        const file = new File([blob], asset.filename, { type: asset.mimeType });
        // Shared manual-attachment code retains request limits and input_audio encoding.
        const result = await chatAttachmentFromFile(file, model, conversationAttachments(exchanges));
        if (!contextUnchanged()) return;
        if (result.error) throw new Error(result.error);
        if (result.attachment) {
          if (result.attachment.modality === 'image') {
            // Image pixel limits are checked only for image samples.
            const bitmap = await createImageBitmap(file);
            const candidate = { ...result.attachment, width: bitmap.width, height: bitmap.height };
            bitmap.close();
            if (!contextUnchanged()) return;
            const imageError = validateChatAttachments(model, [...conversationAttachments(exchanges), candidate]);
            if (imageError) throw new Error(imageError);
            sampleAttachments.push(candidate);
          } else {
            sampleAttachments.push(result.attachment);
          }
        }
      }
      if (!contextUnchanged()) return;
      const plannedSettings = { ...session.settings, ...patch };
      const validation = buildChatRequest(model, plannedSettings, exchanges, example.prompt, sampleAttachments);
      if (validation.error) throw new Error(validation.error);
      if (!contextUnchanged()) return;
      session.updateSettings(patch);
      setDraft(example.prompt);
      setAttachments(sampleAttachments);
      setAppliedExampleId(example.id);
      setInputError(null);
      setConfirmExampleReplace(false);
      setShowExamples(false);
      setFocusComposerAfterExample(true);
    } catch (reason) {
      if (contextUnchanged()) {
        setExampleError(reason instanceof Error ? reason.message : '예제를 적용하지 못했습니다.');
      }
    } finally {
      if (sequence === applySequenceRef.current) setExampleLoading(false);
    }
  }

  function submit() {
    if (attachmentBusy || exampleLoading || pendingModelId !== null) return;
    const text = draft.trim();
    if ((!text && attachments.length === 0) || model === null) return;
    const error = send(model, text, attachments);
    setInputError(error);
    if (error === null) {
      setDraft('');
      setAttachments([]);
      setAppliedExampleId(null);
      followRef.current = true;
      setShowExamples(false);
    }
  }

  function commitModelChange(nextId: string, resetConversation = false) {
    if (busy || attachmentBusy || exampleLoading || pendingToolExchange) return;
    const nextModel = models.find((item) => item.id === nextId);
    if (!nextModel) {
      setPendingModelId(null);
      return;
    }
    // Recompute on confirmation: current settings/history can change while pending.
    const plan = planModelSwitch(nextModel, session.settings, exchanges, attachments, draft);
    if (plan.conversationError && !resetConversation) {
      setPendingModelId(nextId);
      return;
    }
    cancelExamplePreparation();
    if (resetConversation) {
      clear();
      setShowExamples(true);
    }
    setSelectedId(nextId);
    setAttachments([]);
    setAppliedExampleId(null);
    setSelectedExampleId(null);
    setExampleError(null);
    setInputError(null);
    setPendingModelId(null);
    if (Object.keys(plan.settingsPatch).length > 0) {
      session.updateSettings(plan.settingsPatch);
    }
  }

  function requestModelChange(nextId: string) {
    if (model?.id === nextId) {
      setPendingModelId(null);
      return;
    }
    if (busy || exampleLoading || attachmentBusy || pendingToolExchange) return;
    const nextModel = models.find((item) => item.id === nextId);
    if (!nextModel) return;
    const plan = planModelSwitch(nextModel, session.settings, exchanges, attachments, draft);
    if (plan.requiresConfirmation || plan.conversationError) {
      setPendingModelId(nextId);
    } else {
      commitModelChange(nextId);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중 Enter는 글자 확정이다. 보내면 마지막 글자가 잘린다.
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!busy) submit();
  }

  return (
    <section className="chat-page" aria-labelledby="chat-workspace-title">
      <div className="playground-panel-heading">
        <div>
          <h2 id="chat-workspace-title">Chat Completions</h2>
          <p>대화와 첨부는 현재 탭에만 유지됩니다.</p>
        </div>
        <div className="chat-heading-actions">
          <Button type="button" variant="secondary" onClick={() => {
            cancelExamplePreparation();
            setShowExamples((current) => !current);
            setExampleError(null);
          }}>{showExamples ? '예제 닫기' : '예제 보기'}</Button>
          <a className="chat-settings-jump" href="#chat-model-settings">요청 설정 ↓</a>
          {exchanges.length > 0 ? <Button variant="secondary" onClick={() => {
            cancelExamplePreparation();
            clear();
            setAppliedExampleId(null);
            setPendingModelId(null);
            setShowExamples(true);
          }}>대화 지우기</Button> : null}
        </div>
      </div>

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
        <>
          <div className="chat-model-bar">
            <div className="chat-model-selection">
              {models.length > 1 ? (
                <>
                  <label htmlFor="chat-model">현재 모델</label>
                  <select
                    id="chat-model"
                    value={model.id}
                    onChange={(event) => requestModelChange(event.currentTarget.value)}
                    disabled={busy || exampleLoading || attachmentBusy || pendingToolExchange !== null}
                  >
                    {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
                  </select>
                </>
              ) : <span className="chat-model-selection-label">현재 모델</span>}
            </div>
            <ModelContext model={model} showIdentity={models.length === 1} />
            {pendingModel && pendingSwitchPlan ? (
              <div className="chat-model-change-confirm" role="group" aria-label="모델 변경 확인">
                <strong>{model.id} → {pendingModel.id}</strong>
                <span role="status">
                  {pendingSwitchPlan.conversationError
                    ? '대상 모델에서 기존 대화를 이어갈 수 없습니다. 대화를 지운 뒤 변경하세요.'
                    : `${exchanges.length ? '기존 대화 유지 · ' : ''}${attachments.length ? '첨부 파일 제거 · ' : ''}${pendingSwitchPlan.affectedSettings.length ? '일부 요청 설정 조정' : '요청 설정 유지'}`}
                </span>
                <Button size="sm" variant="secondary" onClick={() => setPendingModelId(null)}>취소</Button>
                {pendingSwitchPlan.conversationError ? (
                  <Button size="sm" variant="danger" isDisabled={busy || attachmentBusy || exampleLoading} onClick={() => commitModelChange(pendingModel.id, true)}>대화 지우고 변경</Button>
                ) : (
                  <Button size="sm" isDisabled={busy || attachmentBusy || exampleLoading} onClick={() => commitModelChange(pendingModel.id)}>모델 변경</Button>
                )}
              </div>
            ) : null}
          </div>
          <div className="chat-layout">
            <div className="chat-main">
            {showExamples ? (
              <PlaygroundExampleGallery
                model={model}
                controls={chatControls(model)}
                selectedId={selectedExampleId}
                sampleUrls={SAMPLE_URLS}
                validateRequest={validateExampleRequest}
                busy={busy || attachmentBusy || exampleLoading || pendingToolExchange !== null || pendingModelId !== null}
                hasConversation={exchanges.length > 0}
                confirmReplace={confirmExampleReplace}
                error={exampleError}
                onSelect={(id) => {
                  cancelExamplePreparation();
                  setSelectedExampleId(id);
                  setExampleError(null);
                }}
                onApply={(example) => { void applyExample(example); }}
                onCancelReplace={() => setConfirmExampleReplace(false)}
              />
            ) : null}
            {exchanges.length > 0 ? (
              <ol className="chat-log" aria-live="polite" aria-atomic="false" aria-relevant="additions text">
                {exchanges.map((exchange) => (
                  <ExchangeView
                    key={exchange.id}
                    exchange={exchange}
                    grafanaUrl={grafanaUrl}
                    docsUrl={docsUrl}
                    pendingToolResult={pendingToolExchange?.id === exchange.id}
                    busy={busy}
                    onSendToolResults={(sourceExchangeId, results) => sendToolResults(model, sourceExchangeId, results)}
                  />
                ))}
              </ol>
            ) : null}
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                if (busy) stop();
                else submit();
              }}
            >
              {appliedExampleId ? (
                <div className="chat-applied-example" role="status">
                  <span aria-hidden="true">✓</span>
                  <span>
                    {PLAYGROUND_EXAMPLES.find((item) => item.id === appliedExampleId)?.title} 예제에서 시작
                    {attachments.length ? ` · ${exampleAttachmentSummary(attachments)}` : ''}
                  </span>
                  <button type="button" onClick={() => setAppliedExampleId(null)} aria-label="예제 적용 표시 닫기">×</button>
                </div>
              ) : null}
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
                ref={composerRef}
                disabled={pendingToolExchange !== null || attachmentBusy || exampleLoading || pendingModelId !== null}
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
                      disabled={busy || attachmentBusy || exampleLoading || pendingToolExchange !== null || pendingModelId !== null}
                      onChange={(event) => { void onAttachmentsSelected(event); }}
                    />
                  </div>
                ) : <small>현재 모델은 파일 입력을 광고하지 않습니다.</small>}
              </div>
              <div className="chat-composer-actions">
                {inputError ? <p className="form-error" role="alert">{inputError}</p>
                  : exampleLoading ? <span>예제 파일 준비 중…</span>
                    : attachmentBusy ? <span>첨부 파일 읽는 중…</span> : <span />}
                {busy ? (
                  <Button type="submit" variant="danger">중지</Button>
                ) : (
                  <Button
                    type="submit"
                    variant="primary"
                    isDisabled={pendingToolExchange !== null || attachmentBusy || exampleLoading || pendingModelId !== null || (!draft.trim() && attachments.length === 0)}
                  >
                    보내기
                  </Button>
                )}
              </div>
            </form>
            <div ref={conversationEndRef} className="chat-conversation-end" aria-hidden="true" />
          </div>
            <aside className="chat-side" id="chat-model-settings" aria-label="요청 설정">
              <ChatSettingsPanel model={model} />
              <a className="chat-back-link" href="#chat-input">대화 입력으로 돌아가기 ↑</a>
            </aside>
          </div>
        </>
      ) : null}
    </section>
  );
}
