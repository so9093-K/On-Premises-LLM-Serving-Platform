import { Button } from '@patternfly/react-core';
import { exampleAttachmentSummary, exampleAvailability, exampleRequiresFreshConversation, EXAMPLE_SAMPLE_ASSETS, PLAYGROUND_EXAMPLES, videoExampleLimitSummary, type ExampleSampleId, type PlaygroundExample } from './playgroundExamples';
import type { ChatControls, PublicModel } from './chatSession';

type Props = {
  model: PublicModel;
  controls: ChatControls;
  selectedId: string | null;
  sampleUrls: Record<ExampleSampleId, string>;
  validateRequest: (example: PlaygroundExample) => string | null;
  busy: boolean;
  hasConversation: boolean;
  confirmReplace: boolean;
  error: string | null;
  onSelect: (id: string) => void;
  onApply: (example: PlaygroundExample) => void;
  onCancelReplace: () => void;
};

const CATEGORY_MARK: Record<PlaygroundExample['category'], string> = {
  text: 'Aa',
  image: '▧',
  audio: '♫',
  video: '▷',
  structured: '{}',
};

export function PlaygroundExampleGallery({
  model, controls, selectedId, sampleUrls, validateRequest, busy, hasConversation, confirmReplace,
  error, onSelect, onApply, onCancelReplace,
}: Props) {
  const selected = PLAYGROUND_EXAMPLES.find((item) => item.id === selectedId) ?? null;
  const availability = selected ? exampleAvailability(selected, model, controls, validateRequest) : null;
  const videoLimits = selected?.category === 'video' ? videoExampleLimitSummary(model) : '';
  const needsFreshConversation = selected !== null && hasConversation && exampleRequiresFreshConversation(selected);
  const unavailableReason = needsFreshConversation
    ? '새 대화에서 사용할 수 있습니다. 기존 대화를 지운 뒤 적용하세요.'
    : availability?.reason;

  return (
    <section className="playground-examples" aria-label="시작 예제">
      <h2>예제로 시작하기</h2>
      <div className="playground-example-grid" role="group" aria-label="예제 선택">
        {PLAYGROUND_EXAMPLES.map((example) => {
          const support = exampleAvailability(example, model, controls, validateRequest);
          return (
            <button
              className={`playground-example-card${selectedId === example.id ? ' is-selected' : ''}${support.available ? '' : ' is-unavailable'}`}
              type="button"
              key={example.id}
              aria-pressed={selectedId === example.id}
              onClick={() => onSelect(example.id)}
              disabled={busy}
            >
              <span className="playground-example-card-heading">
                <span className="playground-example-mark" aria-hidden="true">{CATEGORY_MARK[example.category]}</span>
                <span className="playground-example-title">{example.title}</span>
                {selectedId === example.id ? <span className="playground-example-check" aria-hidden="true">✓</span> : null}
              </span>
              <span className="playground-example-description">{example.description}</span>
              {!support.available ? <span className="playground-example-unavailable">{support.reason}</span> : null}
            </button>
          );
        })}
      </div>
      {selected ? (
        <div className="playground-example-preview" aria-live="polite">
          <div className="playground-example-preview-heading">
            <h3>{selected.title}</h3>
            <div className="playground-example-tags" aria-label="적용할 입력 종류">
              {selected.sample ? <span>{exampleAttachmentSummary([EXAMPLE_SAMPLE_ASSETS[selected.sample]])}</span> : null}
              {selected.systemPrompt ? <span>시스템 프롬프트</span> : null}
              {selected.schema ? <span>JSON Schema</span> : null}
              {!selected.sample && !selected.systemPrompt && !selected.schema ? <span>텍스트 입력</span> : null}
            </div>
          </div>
          <p className="playground-example-prompt">{selected.prompt}</p>
          {selected.sample ? (
            <figure className="playground-example-sample">
              {EXAMPLE_SAMPLE_ASSETS[selected.sample].modality === 'audio' ? (
                <audio
                  key={selected.sample}
                  className="playground-example-audio"
                  src={sampleUrls[selected.sample]}
                  controls
                  preload="metadata"
                  aria-label="예제 한국어 음성 재생"
                >
                  오디오 재생을 지원하지 않는 브라우저입니다.
                </audio>
              ) : EXAMPLE_SAMPLE_ASSETS[selected.sample].modality === 'video' ? (
                <video
                  key={selected.sample}
                  className="playground-example-video"
                  src={sampleUrls[selected.sample]}
                  controls
                  playsInline
                  preload="metadata"
                  aria-label="예제 영상 재생"
                >
                  영상 재생을 지원하지 않는 브라우저입니다.
                </video>
              ) : (
                <img
                  src={sampleUrls[selected.sample]}
                  alt={EXAMPLE_SAMPLE_ASSETS[selected.sample].imageAlt ?? '예제 이미지'}
                  loading="lazy"
                />
              )}
              <figcaption>{EXAMPLE_SAMPLE_ASSETS[selected.sample].caption}</figcaption>
            </figure>
          ) : null}
          {videoLimits ? <p className="playground-example-limits">현재 모델의 영상 입력 상한: {videoLimits}</p> : null}
          {selected.sampleSceneDescription ? (
            <details className="playground-example-technical">
              <summary>영상 장면 설명 보기</summary>
              <p>{selected.sampleSceneDescription}</p>
            </details>
          ) : null}
          {selected.sampleTranscript ? (
            <details className="playground-example-technical">
              <summary>음성 대본 보기</summary>
              <p>{selected.sampleTranscript}</p>
            </details>
          ) : null}
          {selected.systemPrompt || selected.schema ? (
            <details className="playground-example-technical">
              <summary>{selected.schema ? 'JSON Schema 보기' : '시스템 프롬프트 보기'}</summary>
              {selected.systemPrompt ? <p>{selected.systemPrompt}</p> : null}
              {selected.schema ? <pre>{selected.schema.value}</pre> : null}
            </details>
          ) : null}
          {unavailableReason ? <p className="playground-example-warning" role="status">{unavailableReason}</p> : null}
          {error ? <p className="playground-example-warning" role="alert">{error}</p> : null}
          {confirmReplace ? (
            <div className="playground-example-confirm" role="group" aria-label="입력 교체 확인">
              <p>현재 작성 중인 입력과 일부 요청 설정을 교체합니다.</p>
              <div className="playground-example-actions">
                <Button variant="secondary" onClick={onCancelReplace} isDisabled={busy}>취소</Button>
                <Button onClick={() => onApply(selected)} isDisabled={busy || Boolean(unavailableReason)}>교체하고 적용</Button>
              </div>
            </div>
          ) : (
            <div className="playground-example-actions">
              <Button onClick={() => onApply(selected)} isDisabled={busy || Boolean(unavailableReason)}>
                입력에 적용
              </Button>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
