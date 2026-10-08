// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const SID = "0b6f3c1e-4d2a-4f8b-9c3e-2a1d5e6f7a8b";
const URL_ = `http://web/api/sessions/${SID}/estimate/stream`;
const HOST = { host: "localhost:3000" }; // the BFF answers only its own Host (session 3 guard in proxy.ts)

const sse = () => new Response("event: status\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } });
const turn = (fields: Record<string, string> = {}, files: File[] = [new File(["%PDF-1.7"], "spec.pdf", { type: "application/pdf" })]) => {
  const form = new FormData();
  const all = { transcript: "turn one", project_type: "web_saas", detail_level: "medium", output_format: "phases_table", ...fields };
  for (const [key, value] of Object.entries(all)) form.set(key, value);
  for (const file of files) form.append("attachments", file);
  return form;
};
const post = (body: BodyInit, headers: Record<string, string> = {}, url = URL_) => new Request(url, { method: "POST", body, headers: { ...HOST, ...headers } });
const call = (req: Request, id = SID) => POST(req, { params: Promise.resolve({ id }) });
const errorOf = async (res: Response) => (await res.json()).error;

beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

it("re-sends the validated form to the AI service and propagates abort", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sse());
  const req = post(turn());
  const res = await call(req);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`http://ai-service:8000/sessions/${SID}/estimate/stream`);
  const sent = (init as RequestInit).body as FormData;
  expect(sent.get("transcript")).toBe("turn one");
  expect((sent.get("attachments") as File).name).toBe("spec.pdf");
  expect(new Headers((init as RequestInit).headers).has("content-type")).toBe(false);
  expect((init as RequestInit).signal).toBe(req.signal);
  expect(res.headers.get("cache-control")).toMatch(/no-transform/);
});

it("rejects a disallowed file type before calling upstream", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch");
  const res = await call(post(turn({}, [new File(["MZ"], "virus.exe", { type: "application/octet-stream" })])));
  expect(res.status).toBe(422);
  expect(await errorOf(res)).toEqual({ code: "invalid_attachment", message: "virus.exe: unsupported file type (PDF, DOCX or plain text only)" });
  expect(fetchMock).not.toHaveBeenCalled();
});

it("rejects a session id that is not a UUID before calling upstream", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch");
  const res = await call(post(turn(), {}, "http://web/api/sessions/x/estimate/stream"), "../x");
  expect(res.status).toBe(404);
  expect((await errorOf(res)).code).toBe("session_not_found");
  expect(fetchMock).not.toHaveBeenCalled();
});

describe("the turn form", () => {
  it("forwards only the fields the AI service accepts, every file, and a non-empty output language", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sse());
    const files = [new File(["%PDF-1.7"], "spec.pdf", { type: "application/pdf" }), new File(["notes"], "Notes.TXT", { type: "" })];
    await call(post(turn({ output_language: "Spanish", model: "gpt-5", session_id: "other" }, files)));
    const sent = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect([...new Set(sent.keys())].sort()).toEqual(["attachments", "detail_level", "output_format", "output_language", "project_type", "transcript"]);
    expect(sent.getAll("attachments").map((file) => (file as File).name)).toEqual(["spec.pdf", "Notes.TXT"]);
    expect(sent.get("output_language")).toBe("Spanish");

    await call(post(turn({ output_language: "" }, [])));
    const second = (fetchMock.mock.calls[1][1] as RequestInit).body as FormData;
    expect(second.has("output_language")).toBe(false); // empty means "not given": not forwarded
    expect(second.has("attachments")).toBe(false);
  });

  it("never forwards Host, cookies or other incoming headers, only accept and the request id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sse());
    await call(post(turn(), { cookie: "a=b", authorization: "Bearer t", "x-request-id": "req-7", "sec-fetch-site": "same-origin", origin: "http://localhost:3000" }));
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect([...headers.keys()].sort()).toEqual(["accept", "x-request-id"]);
    expect(headers.get("x-request-id")).toBe("req-7");
    expect((fetchMock.mock.calls[0][1] as RequestInit).redirect).toBe("error");
  });

  it.each([
    ["an unknown project type", { project_type: "spaceship" }, "project_type"],
    ["an unknown detail level", { detail_level: "everything" }, "detail_level"],
    ["an unknown output format", { output_format: "poem" }, "output_format"],
    ["a blank transcript", { transcript: "  " }, "transcript"],
    ["an output language over 40 characters", { output_language: "x".repeat(41) }, "output_language"],
  ])("rejects %s with 422 invalid_request, naming the field", async (_, fields, field) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const res = await call(post(turn(fields)));
    expect(res.status).toBe(422);
    const error = await errorOf(res);
    expect(error.code).toBe("invalid_request");
    expect(error.message).toContain(field);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a missing field", async () => {
    const form = turn();
    form.delete("detail_level");
    const res = await call(post(form));
    expect(res.status).toBe(422);
    expect((await errorOf(res)).message).toContain("detail_level");
  });

  it("rejects a file sent as text, too many files, and a file over 10 MB, naming the file", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const asText = turn({ attachments: "not a file" }, []);
    expect(await errorOf(await call(post(asText)))).toMatchObject({ code: "invalid_attachment" });

    const six = Array.from({ length: 6 }, (_, i) => new File(["x"], `n${i}.txt`, { type: "text/plain" }));
    expect(await errorOf(await call(post(turn({}, six))))).toEqual({ code: "invalid_attachment", message: "too many attachments (at most 5 per turn)" });

    const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.pdf", { type: "application/pdf" });
    expect(await errorOf(await call(post(turn({}, [big]))))).toEqual({ code: "invalid_attachment", message: "big.pdf: larger than 10 MB" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // What a browser sends for a file input left empty (undici's own FormData would send it as a text field).
  it("drops an empty file input, as the AI service does", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sse());
    const part = (headers: string, value: string) => `--x\r\nContent-Disposition: form-data; ${headers}\r\n\r\n${value}\r\n`;
    const body = [
      ...Object.entries({ transcript: "turn one", project_type: "web_saas", detail_level: "medium", output_format: "phases_table" }).map(([name, value]) => part(`name="${name}"`, value)),
      part('name="attachments"; filename=""\r\nContent-Type: application/octet-stream', ""),
      "--x--\r\n",
    ].join("");
    await call(post(body, { "content-type": "multipart/form-data; boundary=x" }));
    expect(((fetchMock.mock.calls[0][1] as RequestInit).body as FormData).has("attachments")).toBe(false);
  });

  it("rejects a body that is not multipart without reading it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const req = post(JSON.stringify({ transcript: "x" }), { "content-type": "application/json" });
    const res = await call(req);
    expect(res.status).toBe(422);
    expect((await errorOf(res)).code).toBe("invalid_request");
    expect(req.bodyUsed).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a malformed multipart body", async () => {
    const res = await call(post("garbage", { "content-type": "multipart/form-data; boundary=zzz" }));
    expect(res.status).toBe(422);
    expect((await errorOf(res)).code).toBe("invalid_request");
  });
});

describe("the body limit (5 files of 10 MB plus 1 MiB of fields, as the AI service)", () => {
  const LIMIT = 5 * 10 * 1024 * 1024 + 1024 * 1024;
  // A multipart body the test feeds chunk by chunk, so the proxy's reads can be counted (a FormData body cannot be
  // cancelled mid-way in undici without an unhandled error).
  const streamed = (chunks: () => Uint8Array | null, signal?: AbortSignal) => {
    const seen = { cancelled: false };
    const body = new ReadableStream<Uint8Array>({
      pull: (controller) => {
        const chunk = chunks();
        if (chunk) controller.enqueue(chunk);
      },
      cancel: () => {
        seen.cancelled = true;
      },
    });
    const init: RequestInit & { duplex: "half" } = { method: "POST", body, duplex: "half", signal, headers: { ...HOST, "content-type": "multipart/form-data; boundary=x" } };
    return { req: new Request(URL_, init), seen };
  };

  it("rejects a declared content-length over the limit without reading the body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const req = post(turn(), { "content-length": String(LIMIT + 1) });
    const res = await call(req);
    expect(res.status).toBe(413);
    expect((await errorOf(res)).code).toBe("payload_too_large");
    expect(req.bodyUsed).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stops reading an undeclared body as soon as it goes over the limit", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const chunk = new Uint8Array(1024 * 1024);
    const { req, seen } = streamed(() => chunk);
    const res = await call(req);
    expect(res.status).toBe(413);
    expect(seen.cancelled).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns a bare 499 when the client leaves mid-upload, without calling upstream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const controller = new AbortController();
    let sent = false;
    const { req, seen } = streamed(() => {
      if (sent) return null; // the rest never arrives
      sent = true;
      return new TextEncoder().encode("--x\r\n");
    }, controller.signal);
    const pending = call(req);
    await new Promise((resolve) => setTimeout(resolve, 10));
    controller.abort(new Error("ResponseAborted"));
    const res = await pending;
    expect(res.status).toBe(499);
    expect(seen.cancelled).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("guards and upstream failures", () => {
  it("rejects a foreign Host or a cross-site POST before reading the body", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const foreign = post(turn(), { host: "rebind.attacker.example:3000" });
    const crossSite = post(turn(), { "sec-fetch-site": "cross-site", origin: "https://evil.example" });
    expect([(await call(foreign)).status, (await call(crossSite)).status]).toEqual([403, 403]);
    expect([foreign.bodyUsed, crossSite.bodyUsed]).toEqual([false, false]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the AI service's own error through with its status (an expired session, a busy one)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "session_busy", message: "busy" }, request_id: "r" }, { status: 409 }));
    const res = await call(post(turn()));
    expect(res.status).toBe(409);
    expect((await errorOf(res)).code).toBe("session_busy");
  });

  it("maps an unreachable AI service to 503", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const res = await call(post(turn()));
    expect(res.status).toBe(503);
    expect((await errorOf(res)).code).toBe("upstream_unavailable");
  });
});
