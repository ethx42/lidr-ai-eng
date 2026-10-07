import "server-only";
import { serverEnv } from "./env";

// Fixed paths only: the upstream URL is AI_SERVICE_URL plus code-owned paths, never client input (SSRF guard).
type UpstreamPath = `/api/v1/${string}`;
type Allowlist = Record<string, (value: string) => boolean>;

// The upstream query is rebuilt from allowlisted keys only, each value re-encoded, so a value cannot smuggle in another
// parameter. Each key also checks its value: one the AI service could not accept is dropped, never forwarded.
export const withQuery = (path: UpstreamPath, request: Request, allowed: Allowlist): UpstreamPath => {
  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const [key, accept] of Object.entries(allowed)) {
    const value = incoming.get(key);
    if (value !== null && accept(value)) query.set(key, value);
  }
  const search = query.toString();
  return search ? `${path}?${search}` : path;
};

export const oneOf = (values: readonly string[]) => (value: string) => values.includes(value);
export const matching = (pattern: RegExp) => (value: string) => pattern.test(value);

const DEFAULT_MAX_BODY_BYTES = 2_000_000;
const FORWARDED_HEADERS = ["content-type", "accept"] as const;
const SAFE_REQUEST_ID = /^[A-Za-z0-9._:-]{1,128}$/; // same rule as the AI service

const requestIdOf = (request: Request) => {
  const supplied = request.headers.get("x-request-id");
  return supplied && SAFE_REQUEST_ID.test(supplied) ? supplied : crypto.randomUUID();
};

const errorResponse = (status: number, code: string, message: string, requestId: string) =>
  Response.json({ error: { code, message }, request_id: requestId }, { status, headers: { "x-request-id": requestId } });

// The app has no auth and the AI service spends real keys, so the BFF answers only its own pages. DNS rebinding makes a
// foreign page same-origin with it, but that page's requests still carry the foreign name in Host (a header pages
// cannot set, unlike X-Forwarded-Host). Cross-site POSTs, which browsers mark with Sec-Fetch-Site and Origin, are
// refused too; a client that sends neither (curl) passes.
const rejection = (request: Request, method: "GET" | "POST", allowedHosts: string[]) => {
  const host = request.headers.get("host")?.toLowerCase();
  if (!host || !allowedHosts.includes(host)) return "host";
  if (method === "GET") return null;
  const site = request.headers.get("sec-fetch-site");
  const origin = request.headers.get("origin");
  return (site && site !== "same-origin") || (origin && URL.parse(origin)?.host !== host) ? "cross_site" : null;
};

const forwardedHeaders = (request: Request, requestId: string) => {
  const headers = new Headers({ "x-request-id": requestId });
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
};

const clientLeft = () => new Response(null, { status: 499 }); // nobody reads this

// null when the stream goes over the limit; stops reading as soon as it does. Rejects when `signal` aborts (the client
// left mid-upload): cancelling the reader wakes a read that would otherwise wait for bytes that never come.
const readCapped = async (body: ReadableStream<Uint8Array<ArrayBuffer>>, limit: number, signal: AbortSignal) => {
  signal.throwIfAborted();
  const reader = body.getReader();
  const cancel = () => void reader.cancel(signal.reason).catch(() => {});
  signal.addEventListener("abort", cancel, { once: true });
  try {
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    while (size <= limit) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) return new Blob(chunks);
      chunks.push(value);
      size += value.byteLength;
    }
    await reader.cancel();
    return null;
  } finally {
    signal.removeEventListener("abort", cancel);
  }
};

// Fresh headers only: upstream content-encoding/content-length/transfer-encoding/connection would corrupt the body.
const passThrough = (upstream: Response, requestId: string) =>
  new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "x-request-id": requestId },
  });

const sse = (upstream: Response, requestId: string) =>
  upstream.ok && upstream.body
    ? new Response(upstream.body, {
        headers: {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache, no-transform", // no-transform stops Next's gzip from buffering the stream
          "x-accel-buffering": "no",
          "x-request-id": requestId,
        },
      })
    : passThrough(upstream, requestId);

// The upstream method is fixed per helper, never the incoming one; a GET forwards no body.
const proxy = async (
  request: Request,
  { method, path, maxBodyBytes }: { method: "GET" | "POST"; path: UpstreamPath; maxBodyBytes: number },
  respond: (upstream: Response, requestId: string) => Response,
) => {
  const requestId = requestIdOf(request);
  const env = serverEnv();
  const rejected = rejection(request, method, env.ALLOWED_HOSTS);
  if (rejected) {
    console.warn(JSON.stringify({ event: "request_forbidden", request_id: requestId, reason: rejected, host: request.headers.get("host") }));
    return errorResponse(403, "forbidden", "This API only answers the app's own pages.", requestId);
  }
  const tooLarge = () => errorResponse(413, "payload_too_large", `Request body exceeds ${maxBodyBytes} bytes.`, requestId);
  if (method === "POST" && Number(request.headers.get("content-length")) > maxBodyBytes) return tooLarge();
  const body =
    method === "POST" && request.body
      ? await readCapped(request.body, maxBodyBytes, request.signal).catch((error: unknown) => {
          if (request.signal.aborted) return undefined;
          throw error;
        })
      : undefined;
  if (request.signal.aborted) return clientLeft();
  if (body === null) return tooLarge();
  // request.signal aborts when the browser disconnects, which cancels the upstream call and stream.
  // A redirect would leave the fixed upstream path, so it fails like an unreachable upstream.
  return fetch(`${env.AI_SERVICE_URL}${path}`, {
    method,
    headers: forwardedHeaders(request, requestId),
    body,
    signal: request.signal,
    redirect: "error",
  }).then(
    (upstream) => respond(upstream, upstream.headers.get("x-request-id") ?? requestId),
    // fetch failures only; errors thrown by respond are not caught here
    (error: unknown) => {
      if (request.signal.aborted) return clientLeft();
      if (!(error instanceof TypeError)) throw error;
      console.error(JSON.stringify({ event: "upstream_unavailable", request_id: requestId, path, cause: String(error.cause ?? error.message) }));
      return errorResponse(503, "upstream_unavailable", "The AI service is unreachable. Try again later.", requestId);
    },
  );
};

export const proxySse = (request: Request, path: UpstreamPath, { maxBodyBytes = DEFAULT_MAX_BODY_BYTES }: { maxBodyBytes?: number } = {}) =>
  proxy(request, { method: "POST", path, maxBodyBytes }, sse);

export const proxyJson = (request: Request, path: UpstreamPath) => proxy(request, { method: "GET", path, maxBodyBytes: 0 }, passThrough);
