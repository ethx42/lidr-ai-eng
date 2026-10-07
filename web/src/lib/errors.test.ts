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
  ])("maps %o to %s", (error, action) => {
    const message = toUserMessage(error);
    expect(message.action).toBe(action);
    expect(message.title).not.toBe("");
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

  it("keeps only well-formed details, so the message mapping cannot crash", async () => {
    const res = (details: unknown) => Response.json({ error: { code: "invalid_request", message: "m", details }, request_id: "r" }, { status: 422 });
    expect((await fromErrorResponse(res("string_too_long"))).details).toBeUndefined();
    const error = await fromErrorResponse(res([null, 5, { msg: "no type" }, { type: "string_too_long", msg: "too long" }]));
    expect(error.details).toEqual([{ type: "string_too_long", msg: "too long" }]);
    expect(toUserMessage(error).action).toBe("shorten");
  });
});
