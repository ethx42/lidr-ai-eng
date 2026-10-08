# web-client Specification

## Purpose
The web client is the session workspace page and its server routes (the BFF). The page holds one conversation per browser tab and shows what the session remembers beside its turns. The BFF is the browser's only path to the AI service: it keeps the AI service's address on the server, forwards a fixed set of calls, checks a conversation turn before passing it on, and refuses requests that do not come from the app's own pages, because the app has no auth and the AI service spends real API keys.

## Requirements

### Requirement: BFF request guard
The BFF SHALL answer its proxied routes (`POST /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/estimate/stream`, `GET /api/context`, and `POST /api/estimate/stream`) only when the request's `Host` header, compared as `host:port` and ignoring case, is in `ALLOWED_HOSTS` (default `localhost:3000,127.0.0.1:3000`); it SHALL NOT trust `X-Forwarded-Host`. It SHALL also refuse a POST whose `Sec-Fetch-Site` header is present and not `same-origin`, or whose `Origin` header names another host (`Origin: null` included). A refused request SHALL be answered `403` with error code `forbidden` and the request id, before its body is read, before its session id is checked, and without calling the AI service. `GET /api/health` SHALL stay unguarded and SHALL NOT call the AI service, so the container healthcheck works.

#### Scenario: Rebound host refused
- **WHEN** a request to `/api/estimate/stream?refresh=true` carries `Host: rebind.attacker.example:3000`
- **THEN** the response status is `403` with error code `forbidden`
- **AND** the AI service is not called

#### Scenario: Cross-site POST refused
- **WHEN** a POST to `/api/estimate/stream` carries `Host: localhost:3000` and `Sec-Fetch-Site: cross-site`
- **THEN** the response status is `403` with error code `forbidden`
- **AND** the AI service is not called

#### Scenario: Host checked before the session id
- **WHEN** a `GET /api/sessions/{id}` for the id `../x` carries `Host: rebind.attacker.example:3000`
- **THEN** the response status is `403` with error code `forbidden`, not `404`
- **AND** the AI service is not called

### Requirement: BFF forwarding
The BFF SHALL call the AI service at `AI_SERVICE_URL`, read on the server only, on fixed paths and methods, whatever the incoming URL and method, and SHALL NOT follow redirects:

| BFF route | AI service call |
|---|---|
| `POST /api/sessions` | `POST /sessions` |
| `GET /api/sessions/{id}` | `GET /sessions/{id}` |
| `POST /api/sessions/{id}/estimate/stream` | `POST /sessions/{id}/estimate/stream` |
| `GET /api/context` | `GET /api/v1/context` |
| `POST /api/estimate/stream` | `POST /api/v1/estimate/stream` |

A session id SHALL reach the upstream path only when it is a canonical lowercase dashed UUID, the form the AI service issues; the BFF SHALL answer any other id itself with `404` and error code `session_not_found`, without calling the AI service, so the page recovers as it does from an expired session. Every call SHALL carry an `X-Request-ID`: the client's when it is 1 to 128 characters of letters, digits, `.`, `_`, `:`, or `-`, a generated one otherwise. Besides it, `POST /api/estimate/stream`, `GET /api/context`, and `GET /api/sessions/{id}` SHALL forward only the request body (POST) and the `Content-Type` and `Accept` headers; `POST /api/sessions` SHALL forward nothing the client sent (no body; `Accept: application/json`); and `POST /api/sessions/{id}/estimate/stream` SHALL forward only the form it rebuilt (see `BFF session turn`) with `Accept: text/event-stream`, never the client's `Content-Type`, since the rebuilt form gets its own multipart boundary. The BFF SHALL rebuild the upstream query string from allowlisted parameters only, re-encoding each value, and SHALL forward a parameter only when its value is one the AI service accepts, dropping it otherwise (defence in depth: the AI service validates them too). `POST /api/estimate/stream` SHALL forward `refresh` only when it is `true` and `prompt_version` only when it matches `^v[1-9]\d*$`; the request's project type, detail level, and output format travel in its JSON body and are not forwarded from its query. `GET /api/context` SHALL forward `project_type`, `detail_level`, and `output_format` only when each is one of its enum values (see `estimation-api`), and `prompt_version` under the same pattern. The session routes SHALL forward no query. Nothing else of the query string SHALL reach the AI service. Responses from the AI service, errors included, SHALL pass through with their status and body under fresh headers; a stream SHALL be sent unbuffered (`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`). The single-shot route `POST /api/estimate/stream` SHALL stay for API clients, although the app's page no longer calls it.

#### Scenario: Only allowlisted query and headers forwarded
- **WHEN** a client posts to `/api/estimate/stream?refresh=true&model=gpt-5` with `Cookie` and `Authorization` headers
- **THEN** the AI service receives `POST /api/v1/estimate/stream?refresh=true`
- **AND** the forwarded headers are only `Accept`, `Content-Type`, and `X-Request-ID`

#### Scenario: Prompt version forwarded with the stream
- **WHEN** a client posts to `/api/estimate/stream?refresh=true&prompt_version=v2&model=gpt-5`
- **THEN** the AI service receives `POST /api/v1/estimate/stream?prompt_version=v2&refresh=true`
- **AND** with `prompt_version` `../v1`, `v0`, or an empty value, only `refresh=true` is forwarded

#### Scenario: Context choices forwarded only with valid values
- **WHEN** a client calls `/api/context?project_type=mobile_app&detail_level=detailed&output_format=narrative&prompt_version=v2&refresh=true&foo=1`
- **THEN** the AI service receives exactly `project_type=mobile_app`, `detail_level=detailed`, `output_format=narrative`, and `prompt_version=v2`
- **AND** a call with `project_type=game`, `detail_level=Detailed`, or `prompt_version=V2` forwards none of those parameters

#### Scenario: Session started without client input
- **WHEN** a client posts a JSON body naming a `session_id` to `/api/sessions`, with a `Cookie` header
- **THEN** the AI service receives `POST /sessions` with no body and only the `Accept` and `X-Request-ID` headers
- **AND** its `201` JSON passes through with its status

#### Scenario: Session id that is not a UUID
- **WHEN** a client calls a session route with the id `../x`, `x`, an uppercase UUID, or a UUID followed by `/estimate`
- **THEN** the response status is `404` with error code `session_not_found`
- **AND** the AI service is not called

### Requirement: BFF session turn
`POST /api/sessions/{id}/estimate/stream` SHALL take a `multipart/form-data` body and check it before calling the AI service. Its body limit SHALL be the AI service's (see `Request body limit` in `estimation-api`) at that service's default settings: 5 files of 10 MiB plus 1 MiB, 53,477,376 bytes. The BFF SHALL refuse a declared `Content-Length` over the limit without reading the body, count the body against the limit while it arrives (chunked bodies included) and stop reading once it is over, and count the multipart parts while the body arrives, refusing a body with more parts than a turn form can need before it is parsed. A body that is not `multipart/form-data` SHALL be refused without being read. The BFF SHALL then rebuild the form from these fields only, and refuse it when one breaks its rule:

| Field | Rule |
|---|---|
| `transcript` | required, not blank |
| `project_type`, `detail_level`, `output_format` | required, each one of its enum values (see `estimation-api`) |
| `output_language` | optional, at most 40 characters; forwarded only when not empty |
| `attachments` | each a file; file inputs without a name or without content are dropped, as the AI service drops them; at most 5; each at most 10 MiB, with a `.pdf`, `.docx`, or `.txt` name in any case |

Any other field SHALL NOT reach the AI service. A field problem SHALL be answered `422` with error code `invalid_request` and a message naming the field; an attachment problem with `invalid_attachment` and the AI service's own wording, naming the file. The AI service still detects each file's type from its content and enforces its own settings. When the client leaves while the body is read, the BFF SHALL stop reading and answer `499` with no body, without calling the AI service.

#### Scenario: Turn form rebuilt
- **WHEN** a client posts a turn with the transcript, the three choices, `output_language` `Spanish`, the files `spec.pdf` and `Notes.TXT`, and the extra fields `model` and `session_id`, with `Cookie` and `Authorization` headers
- **THEN** the AI service receives a form with only `transcript`, `project_type`, `detail_level`, `output_format`, `output_language`, and both files
- **AND** the forwarded headers are only `Accept` and `X-Request-ID`

#### Scenario: Attachment refused before the upload goes on
- **WHEN** a turn carries `virus.exe`, six files, or a PDF of 10 MiB plus one byte
- **THEN** the response status is `422` with error code `invalid_attachment` and a message such as `virus.exe: unsupported file type (PDF, DOCX or plain text only)` or `too many attachments (at most 5 per turn)`
- **AND** the AI service is not called

#### Scenario: Turn over the body limit
- **WHEN** a client streams a turn with no `Content-Length` past 53,477,376 bytes
- **THEN** the BFF stops reading and answers `413` with error code `payload_too_large`
- **AND** the AI service is not called

#### Scenario: Too many parts
- **WHEN** a turn's body under the byte limit carries thousands of tiny file parts
- **THEN** the BFF stops reading once the count passes what a turn form can need and answers `422` with error code `invalid_request`, before the form is parsed
- **AND** the AI service is not called

#### Scenario: Body that is not multipart
- **WHEN** a client posts a JSON body to a session turn
- **THEN** the response status is `422` with error code `invalid_request`, and the body is not read

### Requirement: BFF errors
The BFF's own errors SHALL use the AI service's error body, `{"error": {"code": <string>, "message": <string>}, "request_id": <string>}`, with the request id also in `X-Request-ID`:

| Condition | Status | `error.code` |
|---|---|---|
| `Host` outside `ALLOWED_HOSTS`, or a cross-site POST | 403 | `forbidden` |
| A session id that is not a canonical dashed UUID | 404 | `session_not_found` |
| A JSON body over 2,000,000 bytes, or a session turn over 53,477,376 bytes, declared in `Content-Length` or counted while reading | 413 | `payload_too_large` |
| A session turn that is not multipart, cannot be parsed, has too many parts, or has a missing or invalid field | 422 | `invalid_request` |
| A session turn's attachments outside the rules of `BFF session turn` | 422 | `invalid_attachment` |
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

### Requirement: Session workspace
The page SHALL hold one conversation per browser tab. On load it SHALL check the session id kept in the tab's `sessionStorage` with `GET /api/sessions/{id}` and keep that session when the AI service knows it; when it answers `404`, or no id is kept, the page SHALL start a session with `POST /api/sessions`, keep its id, and load its view. A reload SHALL keep the session but not the answers shown: the empty thread SHALL say how many earlier turns the session holds, and new turns SHALL be numbered after them. Each turn SHALL be one multipart request to `POST /api/sessions/{id}/estimate/stream` with the composer's transcript, its three choices, and its attached files, after which the composer's transcript and files SHALL be emptied and its choices kept. Each turn SHALL appear in the thread with its choices, its attachments, its transcript behind a disclosure where each grounded quote is marked and linked to its requirement, its streamed estimate with a Structured / Document view, and, from the second completed turn on, the change in its totals from the previous completed turn. Beside the thread, or above it on narrow screens, the page SHALL show the session's four project facts, marking those the latest completed turn changed (its `metadata_changes`), and the history window as `History n / max turns`, both read from the latest completed turn's response, else from the session view. Only the latest turn streams: a new turn while it answers SHALL be refused with a message, without stopping it. Only a stopped or failed latest turn SHALL offer to run again, with its own transcript, choices, and files; a completed turn SHALL offer no way to run it again, because a second answer would also enter the session's history. "New conversation" SHALL start a new session and empty the thread, the facts, and the meter, asking first while a turn is answering. The inspector's Context tab SHALL show the system prompt for the composer's choices on the session's prompt version.

#### Scenario: Session kept across a reload
- **WHEN** the page loads with a kept session id that the AI service reports with 3 history turns
- **THEN** no session is started, the thread says 3 earlier turns are kept, and the next turn is numbered Turn 4

#### Scenario: Kept session the AI service no longer knows
- **WHEN** the kept session id answers `404`
- **THEN** the page starts a new session, keeps its id, and sends the next turn to that session

#### Scenario: Memory follows the latest turn
- **WHEN** a turn completes with `metadata_changes` `["mentioned_technologies"]` and `history_turns` 2
- **THEN** the Technologies fact is marked Updated and the meter reads `History 2 / 6 turns`

#### Scenario: Only a stopped or failed turn runs again
- **WHEN** a turn completes
- **THEN** it offers no Regenerate, Retry, or Try again
- **AND** when the latest turn is stopped, its Retry sends the same transcript, choices, and files as a new attempt in the same card

#### Scenario: New conversation while a turn answers
- **WHEN** the user picks New conversation while a turn streams, then Start new
- **THEN** the stream stops, a new session is kept, the thread is empty, every fact reads "Not mentioned yet", and the meter reads `History 0 / 6 turns`

### Requirement: Turn error recovery
The page SHALL read an error from the shared error body, and, when a response has none (the AI service's plain-text or `{"detail"}` `413`, a proxy's error page), from its status: `404` as `session_not_found`, `409` as `session_busy`, `413` as `payload_too_large`. A turn refused because another turn holds the session (`session_busy`, as a response or as a stream `error` event) SHALL leave the thread, and its transcript and files SHALL go back to the composer, with a message. A turn whose session is unknown or expired (`session_not_found`) SHALL go back to the composer the same way, and the page SHALL start a new session and say so. A rejected attachment (`invalid_attachment`) SHALL show the AI service's message, which names the file, and offer to put the turn's transcript and files back in the composer. Files put back SHALL replace those the composer holds; the transcript SHALL replace a different draft only after asking. `session_busy`, `attachments_busy`, and `sessions_full` SHALL be offered as retryable.

#### Scenario: Busy session
- **WHEN** a turn is answered `409` with error code `session_busy`
- **THEN** the turn leaves the thread and its transcript and files are back in the composer

#### Scenario: Session lost mid-turn
- **WHEN** a turn's stream ends with an `error` event `session_not_found`
- **THEN** the page starts a new session, says the conversation expired, and puts the message back in the composer

#### Scenario: Body limit answered in plain text
- **WHEN** the AI service answers a turn `413` in plain text
- **THEN** the page reports `payload_too_large` and asks for a shorter transcript or fewer or smaller files

### Requirement: Attachment limits in the client
The composer SHALL check each chosen file before it is attached: a `.pdf`, `.docx`, or `.txt` name in any case, not empty, not already attached, within the per-file size and the file count, giving each refused file a visible reason that names it. It SHALL read the count and the size from `max_attachments` and `max_attachment_bytes` of `GET /api/context` (see `Context endpoint` in `estimation-api`), never above the BFF's own limits (5 files of 10 MiB), and SHALL use the BFF's limits until the context loads or when a value is unreadable. Attached files SHALL show as removable chips with their size.

#### Scenario: Service limits applied
- **WHEN** the context reports `max_attachments` 2 and `max_attachment_bytes` 1024 and the user attaches three PDFs and a 2 KB text file
- **THEN** two files are attached, and the third PDF and the text file are refused with a reason naming each

#### Scenario: Raised service limit capped
- **WHEN** the context reports `max_attachments` 8 and `max_attachment_bytes` of 20 MiB
- **THEN** the composer offers up to 5 files of 10 MB each and refuses a sixth
