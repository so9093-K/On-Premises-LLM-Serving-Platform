import type { paths } from './generated/openapi';
import { captureRequestReceipt, receiptText, type RequestReceipt } from './requestReceipt.ts';

// This path is checked by the generated OpenAPI type contract.
// It is shared by Gateway requests and the generated replay clients.
export const CHAT_COMPLETIONS_PATH = '/v1/chat/completions' satisfies keyof paths;

export type PreparedChatRequest = Readonly<{
  json: string;
  streaming: boolean;
  receipt: RequestReceipt;
}>;

export function prepareChatRequest(body: Record<string, unknown>, media: readonly { data: string }[] = []): PreparedChatRequest {
  // Construct once; no caller may pair an unrelated JSON string with a request body.
  const receipt = captureRequestReceipt(body, media);
  return { json: receiptText(receipt), streaming: body.stream === true, receipt };
}
