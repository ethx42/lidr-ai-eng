import { describe, expect, it } from "vitest";
import { fromErrorResponse, toUserMessage } from "./errors";

describe("toUserMessage", () => {
  it.each([
    [{ code: "upstream_rate_limited", message: "m", retryable: true }, "wait"],
    [{ code: "upstream_unavailable", message: "m", retryable: true }, "retry"],
    [{ code: "stream_interrupted", message: "m", retryable: true }, "retry"],
    [{ code: "invalid_request", message: "m", retryable: false, details: [{ type: "missing" }, { type: "string_too_long", msg: "too long" }] }, "shorten"],
    [{ code: "payload_too_large", message: "m", retryable: false }, "shorten"],
    [{ code: "internal_error", message: "m", retryable: false }, "contact"],
    [{ code: "invalid_request", message: "m", retryable: false, details: [{ type: "extra_forbidden" }] }, "contact"],
    [{ code: "invalid_model_output", message: "m", retryable: false }, "retry"], // another attempt usually validates
    [{ code: "some_new_code", message: "m", retryable: true }, "retry"],
    [{ code: "session_busy", message: "m", retryable: true }, "retry"],
    [{ code: "session_not_found", message: "m", retryable: false }, "retry"],
    [{ code: "attachments_busy", message: "m", retryable: true }, "retry"],
    [{ code: "sessions_full", message: "m", retryable: true }, "retry"],
    [{ code: "invalid_attachment", message: "virus.exe: unsupported file type", retryable: false }, "attachments"],
  ])("maps %o to %s", (error, action) => {
    const message = toUserMessage(error);
    expect(message.action).toBe(action);
    expect(message.title).not.toBe("");
  });
});

describe("toUserMessage for sessions", () => {
  it("shows the AI service's message for a rejected attachment, since it names the file", () => {
    const { title } = toUserMessage({ code: "invalid_attachment", message: "virus.exe: unsupported file type (PDF, DOCX or plain text only)", retryable: false });
    expect(title).toBe("An attachment was rejected: virus.exe: unsupported file type (PDF, DOCX or plain text only).");
  });

  it("says a body that is too large may be the attachments, not only the transcript", () => {
    expect(toUserMessage({ code: "payload_too_large", message: "m", retryable: false }).title).toBe(
      "The message is too large. Shorten the transcript or attach fewer or smaller files, then try again.",
    );
  });

  it("explains a busy conversation and an expired one", () => {
    expect(toUserMessage({ code: "session_busy", message: "m", retryable: true }).title).toBe("This conversation is still answering the previous turn. Try again when it finishes.");
    expect(toUserMessage({ code: "session_not_found", message: "m", retryable: false }).title).toBe("This conversation expired, so a new one was started. Send your message again.");
  });
});

describe("fromErrorResponse", () => {
  it.each([502, 503, 504])("maps a non-JSON %i (a proxy error page) to a retryable upstream_unavailable", async (status) => {
    const error = await fromErrorResponse(new Response("<html>Bad Gateway</html>", { status, headers: { "x-request-id": "req-h" } }));
    expect(error).toMatchObject({ code: "upstream_unavailable", retryable: true, requestId: "req-h" });
  });

  it.each([
    ["a string", '"oops"'],
    ["an array", "[1, 2]"],
    ["an error that is not an object", '{"error": "boom", "request_id": 7}'],
  ])("reads a body that is %s by its status", async (_, body) => {
    const error = await fromErrorResponse(new Response(body, { status: 413, headers: { "content-type": "application/json" } }));
    expect(error).toMatchObject({ code: "payload_too_large", retryable: false, requestId: undefined, details: undefined });
  });

  // The AI service's body limit answers in plain text when Content-Length is set, and `{"detail": …}` when chunked.
  it.each([
    ["plain text", "Request Entity Too Large", "text/plain"],
    ["FastAPI's detail JSON", '{"detail": "Request body too large"}', "application/json"],
  ])("maps a 413 in %s to payload_too_large", async (_, body, type) => {
    const error = await fromErrorResponse(new Response(body, { status: 413, headers: { "content-type": type } }));
    expect(error).toMatchObject({ code: "payload_too_large", retryable: false });
  });

  it.each([
    [404, "session_not_found", false],
    [409, "session_busy", true],
  ])("maps a %i without the JSON error shape to %s", async (status, code, retryable) => {
    expect(await fromErrorResponse(new Response("", { status }))).toMatchObject({ code, retryable });
  });

  it("reads the session codes from the JSON body, and marks the transient ones retryable", async () => {
    const res = (status: number, code: string) => Response.json({ error: { code, message: "m" }, request_id: "r" }, { status });
    expect(await fromErrorResponse(res(503, "attachments_busy"))).toMatchObject({ code: "attachments_busy", retryable: true });
    expect(await fromErrorResponse(res(503, "sessions_full"))).toMatchObject({ code: "sessions_full", retryable: true });
    expect(await fromErrorResponse(res(422, "invalid_attachment"))).toMatchObject({ code: "invalid_attachment", retryable: false, message: "m" });
  });

  it("keeps only well-formed details, so the message mapping cannot crash", async () => {
    const res = (details: unknown) => Response.json({ error: { code: "invalid_request", message: "m", details }, request_id: "r" }, { status: 422 });
    expect((await fromErrorResponse(res("string_too_long"))).details).toBeUndefined();
    const error = await fromErrorResponse(res([null, 5, { msg: "no type" }, { type: "string_too_long", msg: "too long" }]));
    expect(error.details).toEqual([{ type: "string_too_long", msg: "too long" }]);
    expect(toUserMessage(error).action).toBe("shorten");
  });
});
