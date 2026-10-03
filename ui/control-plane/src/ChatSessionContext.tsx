import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { ApiError, postChatCompletion } from './api';
import { readChatStream } from './chatStream';
import {
  applyChatUpdate,
  buildChatRequest,
  buildToolResultRequest,
  createRequestContext,
  completeFromResponse,
  DEFAULT_CHAT_SETTINGS,
  failTurn,
  finishTurn,
  startTurn,
  stopTurn,
  type AssistantTurn,
  type ChatAttachment,
  type ChatSettings,
  type ChatToolResult,
  type Exchange,
  type PublicModel,
} from './chatSession';

// 대화·API 키·진행 중인 stream은 Shell 수명에 묶는다. 다른 화면에 다녀와도 대화가
// 남고, 관리자 키를 지워 Shell이 사라지면 함께 사라진다. 서버와 브라우저 저장소에는
// 아무것도 남기지 않는다(ADR-0027과 같은 원칙).
type ChatSessionValue = {
  apiKey: string | null;
  setApiKey: (key: string | null) => void;
  apiKeyRejected: boolean;
  exchanges: Exchange[];
  settings: ChatSettings;
  updateSettings: (patch: Partial<ChatSettings>) => void;
  busy: boolean;
  send: (model: PublicModel, text: string, attachments?: readonly ChatAttachment[]) => string | null;
  sendToolResults: (model: PublicModel, sourceExchangeId: number, results: readonly ChatToolResult[]) => string | null;
  stop: () => void;
  clear: () => void;
};

const ChatSessionContext = createContext<ChatSessionValue | null>(null);

export function ChatSessionProvider({ children }: PropsWithChildren) {
  const [apiKey, setApiKeyState] = useState<string | null>(null);
  const [apiKeyRejected, setApiKeyRejected] = useState(false);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_CHAT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const nextIdRef = useRef(0);
  // send는 최신 대화·설정으로 요청을 만들어야 하지만 매 token마다 새 함수가 되면
  // 입력창까지 다시 그린다. 최신 값은 ref로 읽는다.
  const latest = useRef({ apiKey, exchanges, settings });
  useEffect(() => {
    latest.current = { apiKey, exchanges, settings };
  }, [apiKey, exchanges, settings]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const setApiKey = useCallback((key: string | null) => {
    setApiKeyState(key);
    setApiKeyRejected(false);
  }, []);

  const updateSettings = useCallback((patch: Partial<ChatSettings>) => {
    setSettings((current) => ({ ...current, ...patch }));
  }, []);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setExchanges([]);
  }, []);

  const executeRequest = useCallback((
    key: string | null,
    model: PublicModel,
    body: Record<string, unknown>,
    exchange: Pick<Exchange, 'user' | 'attachments' | 'toolResults'>,
  ): void => {
    const id = ++nextIdRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setExchanges((items) => [
      ...items,
      {
        id,
        user: exchange.user,
        attachments: [...exchange.attachments],
        ...(exchange.toolResults ? { toolResults: [...exchange.toolResults] } : {}),
        sentAtSeconds: Date.now() / 1000,
        requestContext: createRequestContext(model, body),
        assistant: startTurn(performance.now()),
      },
    ]);
    const update = (change: (turn: AssistantTurn) => AssistantTurn) => {
      setExchanges((items) => items.map((item) => (
        item.id === id ? { ...item, assistant: change(item.assistant) } : item
      )));
    };

    void (async () => {
      try {
        const { response, requestId } = await postChatCompletion(key, body, controller.signal);
        update((turn) => ({ ...turn, requestId }));
        if (body.stream === true && response.body) {
          await readChatStream(response.body, (event) => {
            const now = performance.now();
            update((turn) => applyChatUpdate(turn, event, now));
          });
          const now = performance.now();
          update((turn) => finishTurn(turn, now));
        } else {
          const payload: unknown = await response.json();
          const now = performance.now();
          update((turn) => completeFromResponse(turn, payload, now));
        }
      } catch (reason) {
        const now = performance.now();
        if (controller.signal.aborted) {
          update((turn) => stopTurn(turn, now));
        } else if (reason instanceof ApiError) {
          if (reason.status === 401) setApiKeyRejected(true);
          update((turn) => failTurn(turn, {
            code: reason.code,
            message: reason.status === 401 ? 'API 키가 필요하거나 유효하지 않습니다.' : reason.message,
            requestId: reason.requestId,
          }, now));
        } else {
          update((turn) => failTurn(turn, {
            code: null,
            message: reason instanceof Error ? reason.message : '요청에 실패했습니다.',
          }, now));
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setBusy(false);
      }
    })();
  }, []);

  const send = useCallback((
    model: PublicModel,
    text: string,
    attachments: readonly ChatAttachment[] = [],
  ): string | null => {
    if (abortRef.current !== null) return '이전 응답을 받는 중입니다. 중지한 뒤 다시 보내세요.';
    const { apiKey: key, exchanges: history, settings: current } = latest.current;
    const { body, error } = buildChatRequest(model, current, history, text, attachments);
    if (error) return error;
    executeRequest(key, model, body, { user: text, attachments: [...attachments] });
    return null;
  }, [executeRequest]);

  const sendToolResults = useCallback((
    model: PublicModel,
    sourceExchangeId: number,
    results: readonly ChatToolResult[],
  ): string | null => {
    if (abortRef.current !== null) return '이전 응답을 받는 중입니다. 중지한 뒤 다시 보내세요.';
    const { apiKey: key, exchanges: history, settings: current } = latest.current;
    const { body, error } = buildToolResultRequest(model, current, history, sourceExchangeId, results);
    if (error) return error;
    executeRequest(key, model, body, {
      user: '',
      attachments: [],
      toolResults: [...results],
    });
    return null;
  }, [executeRequest]);

  const value = useMemo(
    () => ({
      apiKey,
      setApiKey,
      apiKeyRejected,
      exchanges,
      settings,
      updateSettings,
      busy,
      send,
      sendToolResults,
      stop,
      clear,
    }),
    [apiKey, setApiKey, apiKeyRejected, exchanges, settings, updateSettings, busy, send, sendToolResults, stop, clear],
  );
  return <ChatSessionContext.Provider value={value}>{children}</ChatSessionContext.Provider>;
}

export function useChatSession(): ChatSessionValue {
  const value = useContext(ChatSessionContext);
  if (value === null) {
    throw new Error('useChatSession must be used inside ChatSessionProvider');
  }
  return value;
}
