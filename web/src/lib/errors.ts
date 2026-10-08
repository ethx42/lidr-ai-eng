import type { StreamError } from "@/lib/estimate/types";

// `attachments`: the turn goes back to the composer, where the rejected file can be removed.
export type UserMessage = { title: string; action: "retry" | "shorten" | "wait" | "contact" | "attachments" };
type Detail = NonNullable<StreamError["details"]>[number];

// Transient failures: the same request can succeed later (the AI service marks 429 and 503 retryable).
const RETRYABLE = new Set(["upstream_rate_limited", "upstream_unavailable", "stream_interrupted", "session_busy", "attachments_busy", "sessions_full"]);
// Only used when an error response has no JSON error body: a proxy error page, or the AI service's body limit, which
// answers 413 in plain text (or FastAPI's `{"detail"}` when the body is chunked). 404 and 409 come only from sessions.
const CODE_BY_STATUS: Record<number, string> = {
  404: "session_not_found",
  409: "session_busy",
  413: "payload_too_large",
  422: "invalid_request",
  429: "upstream_rate_limited",
  502: "upstream_unavailable",
  503: "upstream_unavailable",
  504: "upstream_unavailable",
};

const MESSAGES: Record<string, UserMessage> = {
  upstream_rate_limited: { title: "The AI provider is rate limiting requests. Wait a moment, then try again.", action: "wait" },
  upstream_unavailable: { title: "The AI service is unavailable right now. Try again in a moment.", action: "retry" },
  stream_interrupted: { title: "The connection dropped before the estimate finished. Try again.", action: "retry" },
  // A turn's body also carries its attachments.
  payload_too_large: { title: "The message is too large. Shorten the transcript or attach fewer or smaller files, then try again.", action: "shorten" },
  internal_error: { title: "Something went wrong on our side. Share the request ID with support.", action: "contact" },
  // The service does not retry it, but a new attempt usually produces a valid estimate.
  invalid_model_output: { title: "The model returned an estimate that did not pass validation. Try again.", action: "retry" },
  session_busy: { title: "This conversation is still answering the previous turn. Try again when it finishes.", action: "retry" },
  session_not_found: { title: "This conversation expired, so a new one was started. Send your message again.", action: "retry" },
  attachments_busy: { title: "The AI service is busy reading other documents. Try again in a moment.", action: "retry" },
  sessions_full: { title: "Every conversation slot is in use right now. Try again shortly.", action: "retry" },
};
const TOO_LONG: UserMessage = { title: "The transcript is over the character limit. Shorten it and try again.", action: "shorten" };
const RETRY: UserMessage = { title: "The estimate failed. Try again.", action: "retry" };
const CONTACT: UserMessage = { title: "The estimate could not be completed. Share the request ID with support.", action: "contact" };

export const streamInterrupted = (requestId?: string): StreamError => ({
  code: "stream_interrupted",
  message: "The stream ended before the estimate finished.",
  retryable: true,
  requestId,
});

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : undefined);
const isDetail = (value: unknown): value is Detail => isObject(value) && typeof value.type === "string";

// Error responses from the BFF and the AI service share `{error: {code, message, details?}, request_id}`; the body is
// unchecked wire data, so every field is read through a guard.
export const fromErrorResponse = async (res: Response): Promise<StreamError> => {
  const body: unknown = await res.json().catch(() => null);
  const error = isObject(body) && isObject(body.error) ? body.error : {};
  const code = text(error.code) ?? CODE_BY_STATUS[res.status] ?? "internal_error";
  return {
    code,
    message: text(error.message) ?? `Request failed with HTTP ${res.status}.`,
    retryable: RETRYABLE.has(code),
    requestId: (isObject(body) ? text(body.request_id) : undefined) ?? res.headers.get("x-request-id") ?? undefined,
    details: Array.isArray(error.details) ? error.details.filter(isDetail) : undefined,
  };
};

// The AI service's message names the rejected file and the reason ("scan.pdf: unreadable PDF"); it is plain text.
const rejectedAttachment = (message: string): UserMessage => ({
  title: `An attachment was rejected: ${message.replace(/\.?\s*$/, ".")}`,
  action: "attachments",
});

export const toUserMessage = (error: StreamError): UserMessage =>
  error.code === "invalid_attachment"
    ? rejectedAttachment(error.message)
    : error.code === "invalid_request" && error.details?.some((detail) => detail.type === "string_too_long")
      ? TOO_LONG
      : (MESSAGES[error.code] ?? (error.retryable ? RETRY : CONTACT));
