import { useState, type Ref } from 'react';
import { Button } from '@patternfly/react-core';
import { useChatSession } from './ChatSessionContext';
import {
  chatControls,
  numberControlRangeHint,
  TOOL_CHOICE_DEFAULT,
  TOOL_CHOICE_NAMED,
  type NumberControl,
  type PublicModel,
} from './chatSession';

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

export function ChatSettingsPanel({ model, detailsRef }: { model: PublicModel; detailsRef?: Ref<HTMLDetailsElement> }) {
  const { settings, updateSettings } = useChatSession();
  const controls = chatControls(model);
  const [open, setOpen] = useState(false);
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
    <details ref={detailsRef} className="chat-settings" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>요청 설정 · 시스템 프롬프트 / 출력 길이 / 스트리밍</summary>
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
                도구를 직접 실행한 뒤 결과를 대화에 입력하세요.
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

