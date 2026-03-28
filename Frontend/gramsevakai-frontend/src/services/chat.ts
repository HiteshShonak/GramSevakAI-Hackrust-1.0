import { apiFetch } from "@/services/api";
import type { ChatMessageRequest, ChatMessageResponse } from "@/types/api";

/**
 * Strip <think>...</think> reasoning blocks that some LLM models emit.
 * This is a frontend safety net — the backend also strips these,
 * but double-defense ensures they never appear to users.
 */
function sanitizeMessage(text: string): string {
  if (!text || !text.includes("<think")) return text;
  // Remove complete <think>...</think> blocks
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>/gi, "");
  // Remove orphan <think> tags (unclosed — model cut off mid-thought)
  cleaned = cleaned.replace(/<think>[\s\S]*$/gi, "");
  return cleaned.trim();
}

export async function sendChatMessage(
  request: ChatMessageRequest,
  token: string
): Promise<ChatMessageResponse> {
  const response = await apiFetch<ChatMessageResponse>("/api/v1/chat/message", {
    method: "POST",
    token,
    body: JSON.stringify(request)
  });
  // Sanitize all bot messages to strip any <think> reasoning leakage
  if (response.messages) {
    response.messages = response.messages.map(sanitizeMessage);
  }
  return response;
}
