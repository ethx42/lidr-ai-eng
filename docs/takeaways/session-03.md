# Session 3 takeaways: streaming, fallback, cache and the BFF

Branch `pre-session-03` turned the M1 estimator into a streamed chat: a Next.js UI and BFF in `web/`, an SSE endpoint in the AI service, a fallback router over OpenAI and Anthropic, a Redis exact-match cache, and a replay provider so tests and demos cost nothing. These notes cover what the branch taught. Each topic explains the idea and why it exists, what it costs, what actually happened here (file paths, numbers, bugs), and which alternative would pay off more, and when. Read it with the code open. There is a quiz at the end.

The live smoke run (`make smoke-live`, course-meeting transcript, response cache off):

| Check | Served by | TTFT | Total | Cost |
|---|---|---|---|---|
| OpenAI stream | `openai:gpt-4o-mini` | 2,243 ms | 14,106 ms | US$0.001320 |
| Anthropic stream | `anthropic:claude-haiku-4-5` | 2,295 ms | 27,574 ms | US$0.024460 |
| Forced fallback (dead OpenAI primary) | `anthropic:claude-haiku-4-5` | 1,955 ms | 25,249 ms | US$0.013925 |

All three passed. The whole branch, recordings included, spent about US$0.048 on live calls.

## 1. SSE vs WebSocket vs chunked HTTP

There are three common ways to push a long answer to a browser. Chunked HTTP (often NDJSON, one JSON object per line) just lets the body arrive in pieces; you invent the framing. Server-Sent Events (`text/event-stream`) is still one ordinary HTTP response, with a small standard framing on top: `event:`, `data:`, `id:` and `retry:` lines, a blank line to end an event, `:` lines as comments, and traffic in one direction only. A WebSocket upgrades the connection and then speaks its own protocol, with frames going both ways.

An estimate is one request and one long answer. The only thing the client ever says mid-stream is "stop", and closing the connection says that. SSE gives us named events for free (`status`, `partial`, `result`, `error`), passes through plain HTTP infrastructure (the BFF returns `upstream.body` untouched), and FastAPI 0.141 ships `EventSourceResponse` with a keep-alive comment every 15 s and the anti-buffering headers already set. That made it an easy call.

**Trade-offs.**

- Once the first byte is out, the status is 200 for good. FastAPI turns an `HTTPException` raised inside the generator into `200` with an empty body (verified). So every check that must be a 4xx runs in a dependency, before the stream starts: `checked_request` in `app/routers/estimations.py` answers 422 for an over-long transcript. Anything that fails later travels as an `error` event.
- A stream can simply end, with no terminal event: the process was killed, or a proxy timed out. The client has to treat "EOF without `result` or `error`" as a failure, and `web/src/hooks/use-estimate-stream.ts` maps it to a retryable `stream_interrupted`.
- Proxies buffer unless told otherwise. The BFF sends `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`. The `no-transform` was the part that stopped Next.js from gzip-buffering the whole stream (`web/src/lib/ai-service/proxy.ts`).
- On HTTP/1.1 each open stream holds one of the browser's ~6 connections per origin. HTTP/2 makes that go away.

**When to switch.** WebSocket earns its keep when the exchange is two-way while the answer streams: voice, collaborative editing, tool approvals mid-generation, server pushes to an idle client. You then own framing, heartbeats, reconnection and auth on upgrade, and Next.js route handlers don't do upgrades, so the BFF would need a custom server or a separate socket service. Plain NDJSON suits non-browser consumers (a CLI, another service) that want no protocol at all, at the price of rebuilding event types and the terminal-event rule by hand.

## 2. SSE over POST, and why not `EventSource`

`EventSource` is the browser's built-in SSE client. It only sends GET, with no body and no custom headers, and when the connection drops it reconnects by itself and sends `Last-Event-ID`.

Both properties hurt here. The input is a transcript of up to 50,000 characters, which does not fit in a URL (plenty of servers and proxies cap the request line around 8 KB), and a URL ends up in access logs while this project keeps transcripts out of every log. Automatic reconnection is worse: it re-runs the request, and for an LLM call that is a second paid generation, since nothing on the server can resume the first.

So the hook POSTs with `fetch`, pipes the body through `TextDecoderStream` and `EventSourceParserStream` (eventsource-parser 4.1.1), and reads it with `getReader()`. A `for await` loop over the body would be nicer, but async iteration of `ReadableStream` only arrived in Safari 27 and Next's TypeScript lib doesn't type it. The parser runs with `onError: "terminate"` and a 1 MB `maxBufferSize`. It has no flush, so a final event missing its blank line is dropped at EOF (the SSE spec says so) and the hook counts it as "no terminal event".

**Trade-offs.** We gain a request body, headers for auth later, and an `AbortController` behind the Stop button. We lose reconnection and `Last-Event-ID`: a dropped connection shows up as an error with a Retry action, and Retry pays for a new call.

**The alternative: resumable streams.** Run the generation detached from the HTTP request and append each event to a Redis Stream (`XADD`) under a generation id. The client subscribes, and after a drop it resubscribes with `Last-Event-ID` (`XREAD` from that id), so a network blip costs nothing. Stop becomes an explicit cancel call, because a disconnect no longer means "cancel". The wire format is already prepared for it: every `partial` carries its `seq` as the SSE `id`. Of the alternatives in this file, this is the one I would build first. Do it when dropped connections outnumber real Stops: mobile clients, generations of tens of seconds (Haiku took 27.6 s here), users who switch tabs, or lost calls that cost real money (US$0.024 per Haiku estimate). The bill is a worker model, stream TTLs, a cancel endpoint and a few new ways to fail.

## 3. Streaming structured output and partial parsing

The model streams JSON text token by token, and a prefix such as `{"project_name": "Clinic po` is not valid JSON. A partial parser closes it for you: `jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")` returns `{"project_name": "Clinic po"}`.

What we built (spec D2): providers stream text deltas and the service accumulates them. `PartialSnapshotter` (`app/services/streaming.py`) parses the whole accumulated text on every delta and emits a `partial` event only when the parsed dict changed, at most every 100 ms, plus one unthrottled flush before the terminal event. When the stream ends, the final text is validated against the strict Pydantic model, totals, grounding and markdown are computed in code as in M1, and a single `result` event closes the stream. Doing the parsing on the server means M1's guarantees still hold for the final answer, every client sees the same partial view, and no client has to parse unvalidated half-JSON on its own.

**What bit us.**

- The SDKs' parsing stream helpers misreport truncation. `responses.stream(text_format=)` and `messages.stream(output_format=)` validate as soon as the text block ends, so a truncated answer raises `ValidationError` mid-iteration, before the event that says why (`response.incomplete`, `message_delta.stop_reason`). The service would report "invalid output" when the real cause is "hit the token limit". Both providers therefore send the schema raw, read the stop condition first and validate last. M1 hit the same trap with `parse()`.
- OpenAI's Responses helper does no partial parsing at all, and Anthropic's `parsed_snapshot()` is jiter underneath. Calling jiter ourselves gives one code path for both providers.
- Partials can't be trusted. A trailing number is unstable (`"hours": 1` may become `12`), enum values arrive half-written, and arrays stop mid-item. The web types a partial as `DeepPartial<EstimationBreakdown>`, but TypeScript only checks the top level of wire data, so every nested field goes through a guard in `web/src/lib/estimate/read.ts`, and anything missing or malformed renders as a skeleton.
- Empty or whitespace input raises `ValueError`, and so did every other failure in our jiter probes (a lone surrogate raises `UnicodeEncodeError`, which subclasses it). One `except ValueError` covers malformed partials.

**Cost.** Re-parsing the whole snapshot on every delta is O(n²), and it doesn't matter: 4 µs per delta, 10 ms in total for 2,500 deltas over a 10 KB snapshot. Bandwidth matters more. Each partial carries the whole snapshot, so bytes on the wire grow roughly with the square of the stream length. The throttle caps that: the three recorded gpt-4o-mini streams have 1,057 to 1,357 deltas spread over 8 to 12 s, so a client gets at most ~120 partials instead of over a thousand frames. The throttle is there for bandwidth and React render cost; CPU never needed it.

**Alternatives.** Diffs instead of snapshots (JSON Patch, RFC 6902) send only what changed and let the client apply it; worth it once partial payloads dominate bandwidth, on mobile or with large outputs. A Vercel AI SDK `useObject`-style UI goes further: the server streams text, a client hook parses partial JSON against a schema, and the component receives a typed object that fills in, with abort and state handled. That would replace `useEstimateStream` and most of `read.ts`. The catch is that validation, grounding and totals live in Python here, so they would have to move to TypeScript or arrive in a separate final event. Switch when the AI logic itself lives in a TypeScript route, or when several TypeScript clients consume the stream and adopting the SDK's stream protocol is cheaper than maintaining our hook.

## 4. TTFT and perceived latency

Time to first token (TTFT) is queueing, plus prefill (the model reading ~6,400 input tokens), plus the network. Total latency is TTFT plus output tokens divided by decoding speed. People judge responsiveness by the first change on screen.

The numbers show why streaming was worth the work. The wait before anything appears dropped from 14 to 28 s to about 2.2 s. TTFT was 16% of the total on gpt-4o-mini (2,243 of 14,106 ms) and 8% on Haiku (2,295 of 27,574 ms). The answer did not get any faster.

**Caveats.**

- Our TTFT is the first text delta, and the first delta is `{"`. The first useful render, a project name inside a partial, comes later. "Time to first useful partial" is the better UX metric, and this branch never measured it.
- The UI shows progress before the first token anyway: `status: calling_llm` arrives at once, the skeleton already has the shape of the final layout, and the status steps advance. No spinners (spec §8). Screen readers hear `aria-live="polite"` updates on status and completion only, never per token.
- Metrics are end to end. After a fallback, `latency_ms` counts from the router's first attempt, so the inspector never shows a TTFT larger than the latency. Each failed attempt's own duration sits on its `llm_fallback` log record.
- Prefill is what the provider's prompt cache shortens. The forced-fallback Haiku call started right after the first Haiku call, reached its first token sooner (1,955 vs 2,295 ms) and cost 43% less. That fits a cache read of the system block, but it is a single sample from a run that didn't log usage, so treat it as a guess with good support.
- The fallback is slower and pricier: Haiku took about twice as long end to end and cost about 18 times as much per estimate (US$0.0245 vs US$0.0013).

**Alternatives.** Cut real latency, not only perceived: fewer output tokens (session 4's `detail_level`), a faster model, or no call at all (an exact cache hit). If users act on the first number they see, stream a short summary before the detail. And log p95 TTFT and time to first useful partial in production instead of trusting one smoke run.

## 5. Cancellation propagation and its cost

Stop has to travel the whole chain. If it stops halfway, the provider keeps generating, and billing, for nobody.

1. Stop calls `AbortController.abort()` (`use-estimate-stream.ts`).
2. The browser's fetch aborts. Next.js aborts `request.signal`, which the BFF handed to its upstream `fetch` (`proxy.ts`).
3. Uvicorn sees the disconnect and Starlette cancels the request. The service generator gets `CancelledError` at its current `await`, or `GeneratorExit` if it is parked at a `yield`.
4. Leaving the SDK's `async with client.responses.stream(...)` closes the HTTP response. httpcore2 shields that close, so the TCP connection to the provider closes even inside a cancelled scope.
5. The provider stops generating.

We checked it: `curl --max-time 1` mid-stream logs `outcome=cancelled` at ~1,005 ms, and a browser disconnect through the BFF logs `cancelled` upstream within about a second.

**What Stop saves.** Output tokens are the expensive part. One recorded gpt-4o-mini call with a warm prompt cache used 6,449 input tokens (6,016 cached) and 1,237 output tokens for US$0.001258, and output was US$0.000742 of that, 59%. Haiku charges five times more per output token than per input token. Stopping halfway therefore saves about a third of an OpenAI call and more on Haiku. Whether a provider bills exactly up to the moment the connection closes is up to the provider; we didn't measure it.

There is a blind spot. Output usage only arrives at the end (OpenAI's `response.completed`, Anthropic's final `message_delta`), so a cancelled call logs zero tokens and no cost, and the logs under-report what Stop still cost. A cheap improvement: keep the input count from Anthropic's `message_start` and estimate output from the deltas already seen.

**The bug: FastAPI's SSE producer never closed the generator under backpressure.** The first disconnect test passed (`test_client_disconnect_closes_upstream`). Then review asked what happens when the client reads slowly.

FastAPI runs the endpoint generator in a producer task that pushes into a memory stream with a buffer of one. It iterates with a plain `async for` and never calls `aclose()`. With a slow reader the buffer fills, the producer parks on `send`, and the endpoint generator parks at a `yield`. When the client disconnects, the cancellation lands on the `send`, not on the generator, so the `aclosing(...)` inside the endpoint never ran. The provider stream stayed open until garbage collection, and when GC finally closed it, its `llm_call` record had `request_id='-'`, because it ran outside the request's context.

The fix makes the request own the stream. `service_stream` in `app/routers/estimations.py` creates the generator inside a request-scoped yield dependency. Yield dependencies are entered on the request's exit stack before the SSE producer, so their teardown runs after the producer has been cancelled, in the request task, with its context variables intact. The teardown is `with anyio.move_on_after(1, shield=True): await items.aclose()`. It is shielded because anyio cancellation is level-triggered (any unshielded `await` in a cancelled scope raises again) and bounded so it can never hang. `tests/api/test_stream_disconnect.py::test_slow_client_disconnect_closes_upstream_in_the_request_context` pins it, with uvicorn running in-process, because TestClient and `ASGITransport` buffer the whole body and cannot simulate a disconnect. One wart remains: FastAPI 0.141.1 logs an `ExceptionGroup(BrokenResourceError)` as an unhandled error for that request. The client is already gone by then, so it was deferred as noise.

If I keep one lesson from this branch, it is this one. A disconnect test with a fast reader proves very little.

The same work produced three smaller rules:

- Log a cancellation synchronously. An `await` inside `except CancelledError` gets cancelled again.
- Build and log the final response before the trailing events (the final flush, `validating`). A client that leaves during those still produces exactly one `llm_call` record.
- Write to the cache only after the client has taken the result. The write sits after `yield response`, shielded and bounded to 0.5 s, so a client that left caches nothing (`tests/unit/test_llm_service_cache.py::test_leaving_during_the_trailing_events_caches_nothing`).

**Alternative.** Resumable streams (section 2) separate "connection lost" from "user cancelled". Worth it once lost connections outnumber real Stops.

## 6. Three cache layers and cache-key design

| Layer | What is reused | What it saves | Hits when | On this branch |
|---|---|---|---|---|
| Provider prompt cache | The processed prompt prefix, at the provider | Input cost and prefill time. gpt-4o-mini: cached input US$0.075 vs 0.15 per 1M. Haiku: read 0.10, write 1.25, normal 1.00 | Byte-identical prefix. OpenAI caches automatically and `prompt_cache_key` routes to the same cache; Anthropic needs a `cache_control` breakpoint (5-minute TTL) | Recording the three samples: calls 2 and 3 read 6,016 of ~6,400 input tokens from cache |
| App exact-match | The whole validated response | The whole call: no cost, lookup-sized latency | Identical key | Redis, `app/services/cache.py`, 24 h TTL |
| Semantic | A response to a similar request | The whole call | Embedding similarity above a threshold | Not built (session 4 live content) |

The prompt cache still pays for output and decoding; it only skips re-reading the prefix, and it only works when static content comes first. That is why session 4 orders template blocks static-first.

The exact-match cache will rarely hit in real use, because people seldom paste the same free-text transcript twice. It pays off for retries, double submits, demos and the sample transcripts. Regenerate has to produce a new answer, so it sends `?refresh=true`, which skips the lookup and overwrites the entry.

I measured a hit locally with the replay provider, Redis in a Docker container and the course-meeting sample. The first streamed request took 11.2 s and sent 102 partials. The repeat was a `cache_hit` status and the result: the Redis lookup took 1 to 3 ms and the whole request about 3 ms over HTTP, with one `estimate_cache_hit` record and no `llm_call`. The live gpt-4o-mini call in the smoke run took 14.1 s and cost US$0.0013; a hit pays neither.

A semantic cache hits far more often, and its failures are silent. A transcript that says "no mobile app" can embed close to one that wants a mobile app and receive that estimate. When small differences in the input change the numbers, a false hit is expensive and invisible; for estimates I would not build one. It fits when requests repeat with small variations and approximate answers are acceptable (FAQ bots, classification), with a high threshold, ideally a cheap verifier, and the exact cache kept in front.

**Designing the key.** It must contain every input that shapes the stored bytes, and nothing else. Ours (`cache_key` plus `cache_scope`) covers a cache schema version (bumped when the stored shape changes), the prompt version, SHA-256 over canonical JSON of `[system, user]` (a list, so `("ab", "c")` and `("a", "bc")` hash differently; `test_key_keeps_system_and_user_apart`), the chain of providers allowed to serve, temperature, reasoning effort, max output tokens, the output schema name, and the blended hourly rate and weekly capacity.

**Review finding: rate and capacity were missing.** The plan's key had neither. `enrich()` bakes both into the stored totals and markdown, so after a configuration change the cache would have served old costs and durations, and two deployments sharing one Redis would have read each other's rates. The review of Task 15 caught it, and the key and spec §4.5 were fixed. The mistake is easy to make because the obvious list is the LLM call's inputs. The list that matters is the inputs of whatever produced the stored bytes, and here that includes `enrich()`.

Failures and cancelled streams are never cached, and session 5's conversational endpoints skip the cache because their output depends on history. The key is derived from the transcript, so `cache_error` logs carry only the operation and exception class.

**The cache-hit side channel.** A hit is visible: `metrics.cache_hit`, `cost_usd: 0`, a lookup-sized `latency_ms` and a `cache_hit` status event. Timing alone would give it away anyway (milliseconds against seconds). Anyone who can call the API can therefore test whether a guessed transcript was estimated before. We accepted that, since there is no auth and no tenancy yet, and hiding the flag would not help while the timing still leaks. Once auth exists, the tenant or user goes into the scope, so a hit can never cross that boundary.

## 7. Fail-open

When an optional dependency fails, degrade the feature, not the request. The cache is an optimization, so a Redis outage means "no cache", never an error page. Fail-closed is right when the failure itself is the harm: the live-spend guard (spec D12) refuses to run when it cannot show the budget allows the call.

`RedisCache` catches `RedisError` and `TimeoutError`, logs `cache_error` with the operation and class, and treats a failed read as a miss. After a failed lookup it skips the write (`_store`), because a second timeout would double the latency Redis adds. The client comes from `from_url` with `retry=Retry(NoBackoff(), retries=0)` spelled out; `Redis(host=...)` defaults to ten retries with backoff, and a refused connection took 4.6 s to fail that way.

**Review finding: a Redis that is slow but alive.** The first version set `socket_connect_timeout` and `socket_timeout` to 0.25 s and tested Redis being down. Review asked about a Redis that answers, only slowly. Socket timeouts apply per connect and per read, not per call, and a new redis-py 8.1 connection makes three round trips before the command (`HELLO 3`, `CLIENT MAINT_NOTIFICATIONS`, then the pipelined `CLIENT SETINFO` pair). Against a test server that took 0.2 s per reply, the first GET took 1.014 s, nothing raised, and the log said `cache=miss`. A one-second tax on every request, and the logs gave no hint of it.

The fix puts a wall-clock bound on each whole call: `with anyio.fail_after(0.2): await client.get(key)`. Redis now adds at most ~0.4 s to a request (one get, one set), and ~0.2 s when the lookup fails, thanks to the skip-write rule. Tests: `tests/unit/test_cache.py::test_a_slow_redis_is_cut_off_per_call`, plus `test_a_slow_but_alive_redis_adds_at_most_half_a_second` and `test_a_hung_redis_adds_at_most_half_a_second` in `tests/unit/test_llm_service_cache.py`.

The test had its own bug. `redis.exceptions.TimeoutError` and the builtin `TimeoutError` share a name, and the first version only checked the logged class name, so it passed with the bound deleted (redis-py's own read timeout fired first). The final test makes the slow server answer in 0.1 s, under the socket timeout, spies on the logger, and asserts both the builtin class and an elapsed time of at least the bound. Worth the habit: delete the code under test once and watch the test fail.

In the same local run I stopped the Redis container. Requests kept answering 200 in about 3 ms and logged `cache_error` with `op: get` and `ConnectionError`. A refused connection fails at once, so the 0.2 s bound only matters for a Redis that is slow or hung, which is the case the review found.

Cancelling a redis-py command mid-flight turned out to be safe. The connection is dropped and released, so a late reply is never read as the answer to the next command (verified against a scratch server).

**Trade-off and alternative.** During an outage every request still pays the 0.2 s bound. A breaker that skips Redis for a few seconds after a few errors, like the provider cooldown, would remove that. Add one when traffic is high enough for 0.2 s per request to matter, or when Redis moves off the local network. Socket timeouts are not a deadline; if fail-open must cap latency, cap the whole operation.

## 8. Fallback: triggers, idempotency, cooldowns

`FallbackProvider` (`app/services/providers/fallback.py`) implements the same `LLMProvider` protocol over a chain, by default `openai:gpt-4o-mini` then `anthropic:claude-haiku-4-5`. The service has no idea it is talking to a router.

**Triggers.** The router falls back on availability failures: `UpstreamUnavailable` (connection errors, timeouts, 408, 5xx, overload, protocol and transport failures mid-stream), `UpstreamRateLimited` (429), and exhausted quota (`reason == "insufficient_quota"`). It never falls back on other 4xx errors or on `InvalidModelOutput`. A 400 means our request is wrong, and another provider either hides the bug or fails the same way. A refusal or a truncation is about the content or `max_output_tokens`, and sending it elsewhere is shopping for a different answer at double the cost. Tests: `test_only_availability_failures_fall_back`, `test_does_not_fall_back_on_caller_or_output_errors`.

**Only before the first token.** Once a delta has reached the client, switching would show a partial from one model and then a result from another. After the first token the error propagates as an `error` event, and the UI keeps the partial and offers a retry (`tests/api/test_estimate_stream.py::test_primary_failing_after_tokens_is_an_error_never_a_mixed_answer`). The failure still counts toward the primary's cooldown.

**Idempotency.** An LLM call has no side effects, so retrying it can't corrupt data. It still isn't free, since each attempt may bill and a call that timed out may keep running at the provider, and it isn't deterministic, since a retry gives a different answer. What decides whether a switch is acceptable is what the client has already rendered.

**SDK retries vs router retries.** The SDKs retry the initial request (`LLM_MAX_RETRIES=2`), and the 60 s client timeout applies per read. A primary that accepted connections and never answered could hold a request for about 3 × 60 s before the router even saw an error. The ruling: every provider except the last is built with SDK `max_retries=0`, so the router is the retry, and the last one keeps `LLM_MAX_RETRIES` (`tests/unit/providers/test_factory.py::test_only_the_last_provider_keeps_sdk_retries`). It has a price. A transient blip on the primary is now served by a fallback that costs ~18 times more per estimate, and when every fallback is cooling down, the primary runs alone with no SDK retries, so a single 429 fails the request.

Quota needs its own handling. OpenAI reports exhausted credits as a 429 `insufficient_quota`, Anthropic's tier spend cap is also a 429, and the SDKs would retry both like ordinary rate limits. Each client gets a response hook that reads the 429 body and sets `x-should-retry: false` (`_no_retry_on_quota`, `_no_retry_on_spend_cap`).

**Classification holes found in review.** Most review findings on the AI track were in error mapping, not in the routing logic. A router is only as good as its error classifier, and we found five holes across two SDKs:

1. Type-only errors (OpenAI). An `{"error": {...}}` payload inside a stream raises a bare `APIError`, often with `code: null` and `type: "server_error"`. Mapping by code alone turned an outage into `InvalidModelOutput`, which meant a wrong 502 and no fallback. The mapping now reads `code or type`.
2. SDK `RuntimeError`. OpenAI's stream helper raises `RuntimeError` for events that arrive out of order (anything before `response.created`), and Anthropic's accumulator raises `RuntimeError` or `IndexError`. They escaped the mapping as 500s; now they become `UpstreamUnavailable("stream_protocol")`. `httpx2.StreamError` also subclasses `RuntimeError`, but it means we misused the response, so it is re-raised first.
3. Transport errors mid-stream. Anthropic 1.8 reads the body unwrapped, so a dropped connection raised a raw `httpx2.ReadTimeout` or `RemoteProtocolError`, where OpenAI wraps the same failures. They now map to `UpstreamUnavailable("stream_transport")`.
4. Anthropic's quota signals. None of them mapped to quota: the tier spend cap (429 `rate_limit_error` with `details.error_code == "enforced_spend_limit_reached"` and no `retry-after`), a spend limit you set yourself (400 `invalid_request_error`, "You have reached your specified…"), 402 `billing_error`, and an observed 400 "Your credit balance is too low". All of them now carry `insufficient_quota`.
5. Anthropic's mid-stream `event: error`. It arrives as `APIStatusError` with `status_code == 200`, so classifying by status called an overload a generic upstream error. Classification now goes by `error.type`.

**Cooldown.** Three consecutive availability failures bench a `provider:model` for 30 s, a success resets the streak, and the state lives in the process. One more failure after the window benches it again immediately, because only a success ends a streak. Two gaps were accepted: there is no half-open probe (when the window expires, every concurrent request tries the recovering provider at once), and the state is per worker (fine with one worker).

**Live evidence.** In the forced-fallback check OpenAI pointed at `127.0.0.1:9`, which refuses within milliseconds, and Haiku served: TTFT 1,955 ms, total 25,249 ms, US$0.013925, `fallback_used: true`. The UI shows a `fallback` status and a "Fallback used" badge in the inspector. The logs hold one `llm_fallback` warning per failed attempt, with that attempt's own latency, and one `llm_call` for the attempt that served.

**Alternatives.** A circuit breaker with a half-open probe and its state in Redis, once there is more than one worker or recovery stampedes show up. Hedged requests, which ask a second provider when the first hasn't produced a token by the p95 TTFT: they cut tail latency and double the spend on slow calls, so they suit products where the tail matters more than cost. Or a gateway, which is the next section.

## 9. Router vs gateway

A router is a library inside your process that picks the provider: our `FallbackProvider` (about 170 lines) or LiteLLM Router. A gateway is a separate service every app calls: LiteLLM Proxy, Portkey, Cloudflare AI Gateway, Vercel AI Gateway. It centralizes keys, per-team budgets and rate limits, audit logs, cross-app caching and the egress point.

We wrote our own router (spec D3) to keep native features: Responses structured output, Anthropic `cache_control`, per-model effort profiles, streaming snapshots. A unified API gives you the lowest common denominator of those. The course's own LiteLLM configuration also load-balanced instead of falling back, and the course bypassed it for streaming.

**The LiteLLM incident.** On 2026-03-24, LiteLLM 1.82.7 and 1.82.8 on PyPI were compromised and stole `.env` files and cloud credentials. A routing library runs in the one process that holds every provider key, which makes it about the most attractive target in an AI service. What this repo does about that class of attack: a hash-locked `uv.lock` installed with `uv sync --locked`; keys present only in the `ai-service` container; and, on the web side, pnpm 11's `minimumReleaseAge` (1,440 minutes), which refused `next@16.4.0` on its release day until it was explicitly excluded. The point of a release-age delay is that malicious versions are often caught and pulled within hours.

**Trade-offs.** With our own router we own error classification for every SDK, and section 8 shows that is real work. A gateway does that work for many providers, but it adds a network hop and a single point of failure, concentrates every key in one place, and, if hosted, sees every prompt.

**When to switch.** For one app with two providers, a gateway is overhead. It becomes the obvious choice when several apps or teams call LLMs and need central keys, budgets and audit, when compliance wants a single egress point, or when you want provider-agnostic observability without code changes. Even then, keep a thin in-process layer for the native features the gateway can't pass through.

## 10. BFF and keeping the AI service private

A backend for frontend is a server that belongs to the UI. Here it is the Next.js route handlers in `web/src/app/api/`. The browser calls `/api/estimate/stream` and `/api/context` on its own origin, and the BFF calls `http://ai-service:8000` over the Compose network.

The AI service holds the provider keys and has no auth, so anyone who can reach it can spend them. The BFF is where auth, per-user quotas and business rules will go (the course's Rails app plays this role), and being same-origin means no CORS to configure.

What the BFF does, in `web/src/lib/ai-service/proxy.ts`:

- It builds the upstream URL from `AI_SERVICE_URL` plus a path owned by the code (the `UpstreamPath` type, `/api/v1/${string}`) and never from client input. That is the SSRF guard. The only query string that passes through is `?refresh=true`.
- It forwards only `content-type` and `accept`, and accepts an incoming `x-request-id` only when it matches the service's own pattern.
- It caps the body at 2 MB, counting the bytes actually read, because a chunked body has no `content-length`. Over the cap it answers 413.
- It answers with fresh headers. Upstream `content-encoding`, `content-length`, `transfer-encoding` and `connection` are never copied, and `no-transform` keeps Next from gzip-buffering the SSE.
- It passes `signal: request.signal` upstream, so Stop reaches the AI service.
- It maps an unreachable AI service to a 503 `upstream_unavailable` in the service's own error shape, and answers a client that already left with a bare 499.
- It reads `AI_SERVICE_URL` per request, server-side only, and validates it with `z.url({ protocol })`. `z.httpUrl()` was rejected because it demands a dotted host and refused `http://ai-service:8000`.

**Network posture** (`compose.yaml`). Only `web` publishes a port, on `127.0.0.1:3000`. A security scan found that `compose.dev.yaml` published the AI service as `"8000:8000"`, which binds `0.0.0.0`: anyone on the same Wi-Fi could have spent the keys. It is now `127.0.0.1:8000:8000`, and `web` is loopback-only as well, because its BFF spends the same keys without auth. `tests/test_compose.py` enforces loopback-only ports, no published port for `ai-service` in the base file, and none for Redis anywhere.

**How a key travels.** Keys reach only `ai-service`, through `env_file`. No compose value uses `${…}` interpolation (`test_no_host_shell_interpolation`), so a key exported in the host shell (inside Claude Code, for instance) never leaks into a container; a sentinel value exported in the shell appeared zero times in the resolved config. The e2e stack uses `env_file: !reset []`, because a plain `[]` would be merged with the base list and keep the keys; the replay stack was verified keyless. `docker compose config` prints `env_file` values inline, so validate with `--quiet`. And `Settings(hide_input_in_errors=True)` exists because a startup `ValidationError` used to print a present `OPENAI_API_KEY` in plain text whenever another key was missing.

Still deferred: pinning the upstream method per helper, `redirect: "error"` on the upstream fetch, `no-new-privileges` and `cap_drop`, and a separate backend network.

**Alternatives.** Authenticate at the BFF (Auth.js or Better Auth) and add service-to-service auth, a shared token or mTLS, so the AI service stops relying on network position alone. Do it the day this runs anywhere but localhost. For central keys and budgets across apps, see the gateway in section 9.

## 11. History is not memory

This branch has a visible thread: React state plus `sessionStorage` (`estimator.thread.v1`, the 20 latest completed turns, restored on reload). Every turn is a new, independent call, and the composer says so: "Each message is estimated on its own. Conversation memory arrives in a later version."

History is what the UI shows; memory is what you put into the next model call. The brief's `st.session_state` keeps messages on screen, and the model remembers none of them unless they are sent. "Remembering" is always a decision about context: which past turns, summaries or extracted facts go into the prompt.

Session 3 keeps the two apart on purpose. The exact-match cache keys on the prompt, so with history in the prompt every turn's key would depend on everything before it and the cache would stop hitting; session 5's conversational endpoints skip the cache for exactly this reason. History also grows the input on every turn. Each new turn re-pays the earlier ones (prompt caching softens this), and long contexts dilute the model's attention.

**Alternatives (session 5 and beyond).** A sliding window of N turns with a size cap; facts extracted and stored outside the history (project name, team size, technologies, agreed scope); cumulative summaries and anchors (session 5 live); server-side sessions in Redis or Postgres; memory services such as mem0 or Zep. You need them when follow-ups like "same project, without the mobile app" have to work, which is session 5.

## Quiz

**1.** An over-long transcript gets a proper 422 JSON from the streaming endpoint. Where does that check run, and what would happen if it raised `HTTPException` inside the SSE generator instead?

<details>
<summary>Answer</summary>

It runs in a dependency (`checked_request`), which FastAPI resolves before the response starts. Inside the generator the 200 status and headers are already committed, so FastAPI ends the request as `200` with an empty or truncated body. After the first byte, errors can only travel as an `error` event.
</details>

**2.** Give two reasons the web client does not use `EventSource`, and one thing that choice costs.

<details>
<summary>Answer</summary>

`EventSource` is GET-only, with no body or custom headers, so a 50,000-character transcript would have to go in the URL (too long, and it would land in access logs). It also reconnects on its own, which would re-run a paid generation that the server cannot resume. The cost: no built-in reconnection or `Last-Event-ID`, so a dropped connection becomes an error with a Retry action.
</details>

**3.** A user presses Stop while their browser is reading the stream slowly. Before the fix, what kept running, why, and what fixed it?

<details>
<summary>Answer</summary>

The upstream provider stream kept running until garbage collection. FastAPI's SSE producer iterates the endpoint generator through a buffer of one and never closes it. With the buffer full, the disconnect cancelled the producer's `send` while the generator sat at a `yield`, so the `aclosing` inside the endpoint never ran. The fix creates the generator in a request-scoped yield dependency whose teardown runs after the producer is cancelled, in the request's context, and calls `aclose()` under `anyio.move_on_after(1, shield=True)`.
</details>

**4.** The primary returns an overload error after streaming 40 tokens. What does the router do, and why?

<details>
<summary>Answer</summary>

It re-raises. The client gets an `error` event and keeps the partial. Switching providers at that point would mix one model's partial with another model's result. The failure still counts toward the primary's cooldown.
</details>

**5.** Why is every provider except the last built with SDK `max_retries=0`? What does that cost?

<details>
<summary>Answer</summary>

SDK retries run before the router sees an error, and the timeout is per read, so a primary that never answered could hold a request for about 3 × 60 s before falling back. With the router as the retry, the fallback starts at once. The costs: a transient blip on the primary is served by a fallback that costs about 18 times more here, and when every fallback is cooling down, the primary has no retries at all.
</details>

**6.** What belongs in an exact-match cache key? What was missing on this branch, and what would it have caused?

<details>
<summary>Answer</summary>

Every input that shapes the stored bytes: schema version, prompt version, a hash of the rendered prompt pair, the chain, the generation parameters, the output schema, and anything computed into the response afterwards. The blended hourly rate and weekly capacity were missing, although `enrich()` bakes them into totals and markdown. After a configuration change the cache would have served stale costs and durations, and deployments sharing a Redis would have leaked each other's rates.
</details>

**7.** Redis accepts connections, but every reply takes 200 ms, and the socket timeouts are 0.25 s. What does each request pay, what did the logs say, and what is the fix?

<details>
<summary>Answer</summary>

No timeout fires, because each read finishes under 0.25 s. A new connection makes three round trips before the command, so the first GET took about a second, and the log said `cache=miss`, which hid the problem. The fix is a wall-clock bound on each whole call (`anyio.fail_after(0.2)`): Redis then costs at most ~0.4 s per request, and a tripped bound logs `cache_error`.
</details>

**8.** The chat shows ten earlier turns. Does the model see them? What would it take, and what would break?

<details>
<summary>Answer</summary>

No. Each turn is an independent call, and the thread is UI state in `sessionStorage`. Making the model "remember" means sending past turns, or facts derived from them, in the prompt. Input tokens then grow every turn, each turn re-pays the earlier ones, the exact-match key becomes history-dependent (so those endpoints skip the cache), and you need a window or summaries to stay within the context budget. Session 5 adds that.
</details>
