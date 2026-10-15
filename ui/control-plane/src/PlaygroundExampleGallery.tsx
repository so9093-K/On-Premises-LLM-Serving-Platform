import { Button } from '@patternfly/react-core';
import { exampleAvailability, exampleRequiresFreshConversation, PLAYGROUND_EXAMPLES, type ExampleSampleId, type PlaygroundExample } from './playgroundExamples';
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

export function PlaygroundExampleGallery({
  model, controls, selectedId, sampleUrls, validateRequest, busy, hasConversation, confirmReplace,
  error, onSelect, onApply, onCancelReplace,
}: Props) {
  const selected = PLAYGROUND_EXAMPLES.find((item) => item.id === selectedId) ?? null;
  const availability = selected ? exampleAvailability(selected, model, controls, validateRequest) : null;
  const needsFreshConversation = selected !== null && hasConversation && exampleRequiresFreshConversation(selected);
  const unavailableReason = needsFreshConversation
    ? '이 예제는 시스템 프롬프트 또는 응답 형식을 바꿉니다. 기존 대화를 지운 다음 적용하세요.'
    : availability?.reason;

  return (
    <section className="playground-examples" aria-label="시작 예제">
      <div className="playground-examples-heading">
        <div>
          <h2>예제로 시작하기</h2>
          <p>현재 모델에서 사용할 수 있는 예제를 선택하고 입력을 확인하세요. 선택만으로 실행되지 않습니다.</p>
        </div>
      </div>
      <div className="playground-example-grid" role="group" aria-label="예제 선택">
        {PLAYGROUND_EXAMPLES.map((example) => {
          const support = exampleAvailability(example, model, controls, validateRequest);
          return (
            <button
              className={`playground-example-card${selectedId === example.id ? ' is-selected' : ''}`}
              type="button"
              key={example.id}
              aria-pressed={selectedId === example.id}
              onClick={() => onSelect(example.id)}
              disabled={busy}
            >
              <span className="playground-example-title">{example.title}</span>
              <span className="playground-example-description">{example.description}</span>
              {!support.available ? <span className="playground-example-unavailable">{support.reason}</span> : null}
            </button>
          );
        })}
      </div>
      {selected ? (
        <div className="playground-example-preview" aria-live="polite">
          <h3>{selected.title} · 입력 미리보기</h3>
          <p className="playground-example-prompt">{selected.prompt}</p>
          {selected.sample ? (
            <figure className="playground-example-sample">
              <img src={sampleUrls[selected.sample]} alt={selected.sample === 'chart' ? '예제 요청 수 막대그래프' : '예제 가상 주문서'} loading="lazy" />
              <figcaption>예제 이미지 · 실제 요청에 첨부됩니다.</figcaption>
            </figure>
          ) : null}
          {selected.systemPrompt ? (
            <div className="playground-example-detail">
              <strong>시스템 프롬프트</strong>
              <p>{selected.systemPrompt}</p>
            </div>
          ) : null}
          {selected.schema ? (
            <div className="playground-example-detail">
              <strong>JSON Schema · {selected.schema.name}</strong>
              <pre>{selected.schema.value}</pre>
            </div>
          ) : null}
          <p className="playground-example-hint">
            적용하면 작성 중인 입력과 시스템 프롬프트·응답 형식·도구 정의가 예제에 맞게 바뀝니다.
            기존 고급 생성 설정과 완료된 대화는 유지됩니다.
          </p>
          {unavailableReason ? <p className="playground-example-warning" role="status">{unavailableReason}</p> : null}
          {error ? <p className="playground-example-warning" role="alert">{error}</p> : null}
          {confirmReplace ? (
            <div className="playground-example-confirm" role="group" aria-label="입력 교체 확인">
              <p>작성 중인 입력 또는 일부 요청 설정이 있습니다. 예제 내용으로 교체할까요?</p>
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
