import { describe, expect, it } from "vitest";
import { toUserMessage } from "./errors";

describe("toUserMessage", () => {
  it.each([
    [{ code: "upstream_rate_limited", message: "m", retryable: true }, "wait"],
    [{ code: "upstream_unavailable", message: "m", retryable: true }, "retry"],
    [{ code: "stream_interrupted", message: "m", retryable: true }, "retry"],
    [{ code: "invalid_request", message: "m", retryable: false, details: [{ type: "missing" }, { type: "string_too_long", msg: "too long" }] }, "shorten"],
    [{ code: "payload_too_large", message: "m", retryable: false }, "shorten"],
    [{ code: "internal_error", message: "m", retryable: false }, "contact"],
    [{ code: "invalid_request", message: "m", retryable: false, details: [{ type: "extra_forbidden" }] }, "contact"],
    [{ code: "invalid_model_output", message: "m", retryable: false }, "contact"],
    [{ code: "some_new_code", message: "m", retryable: true }, "retry"],
  ])("maps %o to %s", (error, action) => {
    const message = toUserMessage(error);
    expect(message.action).toBe(action);
    expect(message.title).not.toBe("");
  });
});
