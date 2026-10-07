import type { StreamError } from "@/lib/estimate/types";

export type UserMessage = { title: string; action: "retry" | "shorten" | "wait" | "contact" };
type ErrorBody = { error?: { code?: string; message?: string; details?: StreamError["details"] }; request_id?: string };

// Transient failures: the same request can succeed later (the AI service marks 429 and 503 retryable).
const RETRYABLE = new Set(["upstream_rate_limited", "upstream_unavailable", "stream_interrupted"]);
// Only used when an error response has no JSON body (e.g. a proxy error page).
const CODE_BY_STATUS: Record<number, string> = { 413: "payload_too_large", 422: "invalid_request", 429: "upstream_rate_limited", 503: "upstream_unavailable" };

const MESSAGES: Record<string, UserMessage> = {
  upstream_rate_limited: { title: "The AI provider is rate limiting requests. Wait a moment, then try again.", action: "wait" },
  upstream_unavailable: { title: "The AI service is unavailable right now. Try again in a moment.", action: "retry" },
  stream_interrupted: { title: "The connection dropped before the estimate finished. Try again.", action: "retry" },
  payload_too_large: { title: "The transcript is too long. Shorten it and try again.", action: "shorten" },
  internal_error: { title: "Something went wrong on our side. Share the request ID with support.", action: "contact" },
};
const TOO_LONG: UserMessage = { title: "The transcript is over the character limit. Shorten it and try again.", action: "shorten" };
const RETRY: UserMessage = { title: "The estimate failed. Try again.", action: "retry" };
const CONTACT: UserMessage = { title: "The estimate could not be completed. Share the request ID with support.", action: "contact" };

export const streamInterrupted = (): StreamError => ({
  code: "stream_interrupted",
  message: "The stream ended before the estimate finished.",
  retryable: true,
});

// Error responses from the BFF and the AI service share `{error: {code, message, details?}, request_id}`.
export const fromErrorResponse = async (res: Response): Promise<StreamError> => {
  const body: ErrorBody | null = await res.json().catch(() => null);
  const code = body?.error?.code ?? CODE_BY_STATUS[res.status] ?? "internal_error";
  return {
    code,
    message: body?.error?.message ?? `Request failed with HTTP ${res.status}.`,
    retryable: RETRYABLE.has(code),
    requestId: body?.request_id ?? res.headers.get("x-request-id") ?? undefined,
    details: body?.error?.details,
  };
};

export const toUserMessage = (error: StreamError): UserMessage =>
  error.code === "invalid_request" && error.details?.some((detail) => detail.type === "string_too_long")
    ? TOO_LONG
    : (MESSAGES[error.code] ?? (error.retryable ? RETRY : CONTACT));
