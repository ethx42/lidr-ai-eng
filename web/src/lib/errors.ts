import type { StreamError } from "@/lib/estimate/types";

export type UserMessage = { title: string; action: "retry" | "shorten" | "wait" | "contact" };
type Detail = NonNullable<StreamError["details"]>[number];

// Transient failures: the same request can succeed later (the AI service marks 429 and 503 retryable).
const RETRYABLE = new Set(["upstream_rate_limited", "upstream_unavailable", "stream_interrupted"]);
// Only used when an error response has no JSON error body (e.g. a proxy error page).
const CODE_BY_STATUS: Record<number, string> = {
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
  payload_too_large: { title: "The transcript is too long. Shorten it and try again.", action: "shorten" },
  internal_error: { title: "Something went wrong on our side. Share the request ID with support.", action: "contact" },
  // The service does not retry it, but a new attempt usually produces a valid estimate.
  invalid_model_output: { title: "The model returned an estimate that did not pass validation. Try again.", action: "retry" },
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

export const toUserMessage = (error: StreamError): UserMessage =>
  error.code === "invalid_request" && error.details?.some((detail) => detail.type === "string_too_long")
    ? TOO_LONG
    : (MESSAGES[error.code] ?? (error.retryable ? RETRY : CONTACT));
