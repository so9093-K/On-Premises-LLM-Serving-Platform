import { modelRuntimeLabel, modelServingNotice } from './uiText';
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { Alert, Button, Spinner } from '@patternfly/react-core';
import { Link } from 'react-router-dom';
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
  const { apiKey, credentialRevision, apiKeyRejected, exchanges, selectedModelId, setSelectedModelId, draft, setDraft, attachments, setAttachments, busy, send, sendToolResults, stop, clear } = session;
  const [confirmClear, setConfirmClear] = useState(false);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
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
  const settingsDetailsRef = useRef<HTMLDetailsElement | null>(null);
  const clearConfirmRef = useRef<HTMLDivElement | null>(null);
  const clearTriggerRef = useRef<HTMLButtonElement | null>(null);
  const focusComposerAfterClearRef = useRef(false);
  const followRef = useRef(true);
  const followBeforeConfirmRef = useRef(true);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const conversationScrollRef = useRef<HTMLDivElement | null>(null);

  const modelsQuery = usePublicModels(apiKey, credentialRevision);
  const models = useMemo(
    () => chatCapableModels((modelsQuery.data?.data ?? []) as PublicModel[]),
    [modelsQuery.data],
  );
  const lastContractRef = useRef<string | null>(null);
  const [modelContractChanged, setModelContractChanged] = useState(false);
  useEffect(() => {
    if (!modelsQuery.isSuccess) return;
    // 목록 순서 변화만으로 운영자에게 모델 정책 변경 알림을 표시하지 않는다.
    const currentContract = JSON.stringify([...modelsQuery.data.data].sort((a, b) => a.id.localeCompare(b.id)));
    if (lastContractRef.current !== null && lastContractRef.current !== currentContract) {
      setModelContractChanged(true);
    }
    lastContractRef.current = currentContract;
  }, [modelsQuery.data, modelsQuery.isSuccess]);
  // 최초 기본 모델도 신원으로 고정해 외부 모델 교체 시 다른 모델에 몰래 전송하지 않는다.
  useEffect(() => {
    if (modelsQuery.isSuccess && selectedModelId === null && models.length > 0) {
      setSelectedModelId(models[0].id);
    }
  }, [models, modelsQuery.isSuccess, selectedModelId, setSelectedModelId]);
  const retainedModel = models.find((item) => item.id === selectedModelId) ?? null;
  // 사용 중이던 모델이 배포 변경으로 사라져도 초안을 기본 모델에 조용히 전송하지 않는다.
  const selectionUnavailable = selectedModelId !== null && models.length > 0 && retainedModel === null;
  const model = selectionUnavailable ? null : retainedModel ?? models[0] ?? null;
  const servingNotice = modelServingNotice(model?.serving_policy_status);
  const maxOutputControl = model ? chatControls(model).maxTokens : null;
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;
  // 최근 모델 계약 조회에 실패했다면 이전 캐시만으로 요청 가능 상태를 주장하지 않는다.
  const modelInformationUnavailable = modelsQuery.isError && !needsKey;
  const modelRequestBlocked = servingNotice !== null || modelInformationUnavailable;
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
    composerRef.current?.focus({ preventScroll: true });
    setFocusComposerAfterExample(false);
  }, [focusComposerAfterExample, exampleLoading, attachmentBusy, pendingToolExchange]);

  useEffect(() => {
    if (confirmClear) clearConfirmRef.current?.focus();
    else if (focusComposerAfterClearRef.current && exchanges.length === 0) {
      focusComposerAfterClearRef.current = false;
      composerRef.current?.focus();
    }
  }, [confirmClear, exchanges.length]);

  useEffect(() => {
    if (model === null) return;
    const normalized = normalizeChatSettingsForModel(session.settings, model);
    if (normalized !== session.settings) session.updateSettings(normalized);
  }, [model, session.settings, session.updateSettings]);

  // 스크롤은 대화 영역만 소유한다. 전체 페이지를 움직이지 않으며,
  // 사용자가 이전 응답을 읽는 중이라면 스트리밍 중에도 위치를 빼앗지 않는다.
  const onConversationScroll = () => {
    const region = conversationScrollRef.current;
    if (!region) return;
    followRef.current = conversationEndNearViewport(
      region.scrollHeight - region.scrollTop, region.clientHeight,
    );
  };
  useEffect(() => {
    const region = conversationScrollRef.current;
    if (region && followRef.current) region.scrollTop = region.scrollHeight;
  }, [exchanges, showExamples]);

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
    if ((!text && attachments.length === 0) || model === null || modelRequestBlocked) return;
    const error = send(model, text, attachments);
    setInputError(error);
    if (error === null) {
      followRef.current = true;
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
    setSelectedModelId(nextId);
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
          <p>실제 모델 응답과 전송한 요청을 확인합니다.</p>
        </div>
        <div className="chat-heading-actions">
          <Button type="button" variant="secondary" onClick={() => {
            cancelExamplePreparation();
            setShowExamples((current) => !current);
            setExampleError(null);
          }}>{showExamples ? '예제 닫기' : '예제로 시작하기'}</Button>
          <a className="chat-settings-jump" href="#chat-model-settings" onClick={() => {
            if (settingsDetailsRef.current) settingsDetailsRef.current.open = true;
          }}>요청 설정 ↓</a>
          {exchanges.length > 0 ? <Button ref={clearTriggerRef} variant="secondary" onClick={() => {
            followBeforeConfirmRef.current = followRef.current;
            followRef.current = false;
            setConfirmClear(true);
          }}>대화 지우기</Button> : null}
        </div>
      </div>

      {confirmClear && exchanges.length > 0 ? (
        <div className="chat-clear-confirm" role="group" aria-label="대화 삭제 확인" aria-describedby="chat-clear-confirm-description" tabIndex={-1} ref={clearConfirmRef}>
          <p id="chat-clear-confirm-description">전송한 대화 기록과 함께 보낸 첨부를 삭제합니다. 복구할 수 없으며 생성 중인 응답도 중지됩니다. 작성 중인 메시지와 첨부는 유지됩니다.</p>
          <Button variant="secondary" onClick={() => {
            setConfirmClear(false);
            followRef.current = followBeforeConfirmRef.current;
            clearTriggerRef.current?.focus();
          }}>취소</Button>
          <Button variant="danger" onClick={() => {
            cancelExamplePreparation();
            clear();
            setAppliedExampleId(null);
            setPendingModelId(null);
            setShowExamples(true);
            focusComposerAfterClearRef.current = true;
            setConfirmClear(false);
          }}>대화 삭제 확인</Button>
        </div>
      ) : null}

      {modelContractChanged ? (
        <Alert isInline variant="info" title="공개 모델 정보가 변경됐습니다.">
          <p>모델이나 요청 한도가 외부 운영 작업으로 변경됐을 수 있습니다. 작성 중인 메시지와 이전 응답은 유지됩니다. 현재 모델과 요청 설정을 다시 확인하세요.</p>
          <Button variant="secondary" onClick={() => setModelContractChanged(false)}>변경 확인</Button>
        </Alert>
      ) : null}
      {servingNotice ? (
        <Alert isInline variant="warning" title={servingNotice.title}>
          <p>{servingNotice.description}</p>
          <Link to="/main-model">메인 모델 상태·복구 확인 →</Link>
        </Alert>
      ) : null}
      {modelsQuery.isPending ? (
        <div className="inline-loading"><Spinner size="md" aria-label="모델 목록 불러오는 중" /> 모델 목록을 불러오는 중…</div>
      ) : null}
      {modelsQuery.isError && !needsKey ? (
        <Alert isInline variant="danger" title="모델 목록을 불러오지 못했습니다.">
          <p>{apiErrorMessage(modelsQuery.error)} 최신 모델 정책을 확인하기 전에는 새 요청을 보내지 않습니다.</p>
          <Button variant="secondary" isDisabled={modelsQuery.isFetching}
            onClick={() => { void modelsQuery.refetch(); }}>모델 정보 다시 조회</Button>
        </Alert>
      ) : null}
      {modelsQuery.isSuccess && selectionUnavailable ? (
        <Alert isInline variant="warning" title="이전에 선택한 채팅 모델을 사용할 수 없습니다.">
          <p>미전송 메시지는 유지했습니다. 새 모델의 입력 호환성을 확인하고 요청하세요.</p>
          <Button variant="secondary" onClick={() => {
            setAttachments([]);
            setSelectedModelId(null);
          }}>기본 모델 선택 · 미전송 첨부 제거</Button>
        </Alert>
      ) : modelsQuery.isSuccess && model === null ? (
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
            <div className="chat-scroll-region" ref={conversationScrollRef} onScroll={onConversationScroll} role="region" aria-label="대화와 시작 예제" tabIndex={0}>
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
                    toolSendDisabled={modelRequestBlocked}
                    onSendToolResults={(sourceExchangeId, results) => modelRequestBlocked
                      ? '현재 모델 요청 가능 상태를 확인하지 못했습니다. 도구 결과는 전송하지 않았습니다.'
                      : sendToolResults(model, sourceExchangeId, results)}
                  />
                ))}
              </ol>
            ) : null}
            <div ref={conversationEndRef} className="chat-conversation-end" aria-hidden="true" />
            </div>
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
              <div className="chat-composer-context" aria-label="현재 요청 설정">
                {maxOutputControl ? (
                  <label className="chat-quick-output" htmlFor="chat-request-max-tokens">
                    <span>이번 요청의 최대 출력 토큰</span>
                    <input id="chat-request-max-tokens" type="number" inputMode="numeric" step="1"
                      min={maxOutputControl.minimum && !maxOutputControl.minimum.exclusive ? maxOutputControl.minimum.value : undefined}
                      max={maxOutputControl.maximum && !maxOutputControl.maximum.exclusive ? maxOutputControl.maximum.value : undefined}
                      value={session.settings.maxTokens}
                      placeholder="모델 기본값"
                      onChange={(event) => session.updateSettings({ maxTokens: event.currentTarget.value })}
                    />
                  </label>
                ) : null}
                <small>요청별 출력 제한입니다. 서버 문맥·출력 한도는 메인 모델 실행 설정에서 결정됩니다.</small>
              </div>
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
                    isDisabled={modelRequestBlocked || pendingToolExchange !== null || attachmentBusy || exampleLoading || pendingModelId !== null || (!draft.trim() && attachments.length === 0)}
                  >
                    보내기
                  </Button>
                )}
              </div>
            </form>
          </div>
            <aside className="chat-side" id="chat-model-settings" aria-label="요청 설정">
              <ChatSettingsPanel model={model} detailsRef={settingsDetailsRef} />
              <a className="chat-back-link" href="#chat-input">대화 입력으로 돌아가기 ↑</a>
            </aside>
          </div>
        </>
      ) : null}
    </section>
  );
}
