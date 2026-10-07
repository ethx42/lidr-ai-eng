# web-client Specification

## Purpose
The web client's server routes (the BFF) are the browser's only path to the AI service: they keep the AI service's address on the server, forward a fixed set of calls, and refuse requests that do not come from the app's own pages, because the app has no auth and the AI service spends real API keys.

## Requirements

### Requirement: BFF request guard
The BFF SHALL answer its proxied routes (`POST /api/estimate/stream` and `GET /api/context`) only when the request's `Host` header, compared as `host:port` and ignoring case, is in `ALLOWED_HOSTS` (default `localhost:3000,127.0.0.1:3000`); it SHALL NOT trust `X-Forwarded-Host`. It SHALL also refuse a POST whose `Sec-Fetch-Site` header is present and not `same-origin`, or whose `Origin` header names another host (`Origin: null` included). A refused request SHALL be answered `403` with error code `forbidden` and the request id, before its body is read and without calling the AI service. `GET /api/health` SHALL stay unguarded and SHALL NOT call the AI service, so the container healthcheck works.

#### Scenario: Rebound host refused
- **WHEN** a request to `/api/estimate/stream?refresh=true` carries `Host: rebind.attacker.example:3000`
- **THEN** the response status is `403` with error code `forbidden`
- **AND** the AI service is not called

#### Scenario: Cross-site POST refused
- **WHEN** a POST to `/api/estimate/stream` carries `Host: localhost:3000` and `Sec-Fetch-Site: cross-site`
- **THEN** the response status is `403` with error code `forbidden`
- **AND** the AI service is not called

### Requirement: BFF forwarding
The BFF SHALL call the AI service at `AI_SERVICE_URL`, read on the server only, on fixed paths and methods: `POST /api/estimate/stream` calls `POST /api/v1/estimate/stream` and `GET /api/context` calls `GET /api/v1/context`, whatever the incoming URL and method, and SHALL NOT follow redirects. It SHALL forward only the request body (POST), the `Content-Type` and `Accept` headers, and an `X-Request-ID` (the client's when it is 1 to 128 characters of letters, digits, `.`, `_`, `:`, or `-`, a generated one otherwise); of the query string, only `refresh=true` SHALL reach the AI service. Responses from the AI service, errors included, SHALL pass through with their status and body under fresh headers; a stream SHALL be sent unbuffered (`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`).

#### Scenario: Only allowlisted query and headers forwarded
- **WHEN** a client posts to `/api/estimate/stream?refresh=true&model=gpt-5` with `Cookie` and `Authorization` headers
- **THEN** the AI service receives `POST /api/v1/estimate/stream?refresh=true`
- **AND** the forwarded headers are only `Accept`, `Content-Type`, and `X-Request-ID`

### Requirement: BFF errors
The BFF's own errors SHALL use the AI service's error body, `{"error": {"code": <string>, "message": <string>}, "request_id": <string>}`, with the request id also in `X-Request-ID`:

| Condition | Status | `error.code` |
|---|---|---|
| `Host` outside `ALLOWED_HOSTS`, or a cross-site POST | 403 | `forbidden` |
| Request body over 2,000,000 bytes, declared in `Content-Length` or counted while reading | 413 | `payload_too_large` |
| AI service unreachable, including a redirect | 503 | `upstream_unavailable` |

When the client disconnects while its body is read or before the AI service answers, the BFF SHALL cancel the upstream call and answer `499` with no body.

#### Scenario: Body over the cap
- **WHEN** a client posts a body of 2,000,001 bytes to `/api/estimate/stream`
- **THEN** the response status is `413` with error code `payload_too_large`
- **AND** the AI service is not called

#### Scenario: AI service unreachable
- **WHEN** the connection to the AI service fails
- **THEN** the response status is `503` with error code `upstream_unavailable`

#### Scenario: Client leaves mid-upload
- **WHEN** the client disconnects while the BFF is still reading its body
- **THEN** the BFF answers `499` with no body and does not call the AI service
