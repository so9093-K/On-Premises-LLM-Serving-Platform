import { useState, type FormEvent } from 'react';
import { Button } from '@patternfly/react-core';
import type { ChatToolCall, ChatToolResult, Exchange } from './chatSession';

// Console은 도구를 실행하지 않고, 사용자 입력 결과를 원래 tool_call_id로 반환한다.
export function toolArgumentsAreJson(call: ChatToolCall): boolean {
  try {
    JSON.parse(call.function.arguments);
    return true;
  } catch {
    return false;
  }
}

export function ToolResultForm({
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

