import type { paths } from './generated/openapi';

// This path is checked by the generated OpenAPI type contract.
// It is shared by Gateway requests and the generated replay clients.
export const CHAT_COMPLETIONS_PATH = '/v1/chat/completions' satisfies keyof paths;

export type PreparedChatRequest = Readonly<{
  json: string;
  streaming: boolean;
}>;

export function prepareChatRequest(body: Record<string, unknown>): PreparedChatRequest {
  // Construct once; no caller may pair an unrelated JSON string with a request body.
  return { json: JSON.stringify(body), streaming: body.stream === true };
}
