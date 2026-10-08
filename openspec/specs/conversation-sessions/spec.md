# conversation-sessions Specification

## Purpose
Lets a client refine one estimate over several turns: a session keeps a sliding window of the conversation and the project facts learned so far, each turn can attach PDF, DOCX or plain-text documents whose text joins the prompt, and turns are estimated blocking or streamed with the session's prompt version (`v3`), outside the response cache.

## Requirements

### Requirement: Session creation
The system SHALL expose `POST /sessions`, which creates an empty session (no history, empty project metadata) without calling any LLM provider and responds `201` with `{"session_id": "<id>"}`, the id a dashed UUID4 string. When the store is at its cap and every session has a turn in flight, it SHALL respond `503` with error code `sessions_full` (see `Session store lifecycle`).

#### Scenario: Session created
- **WHEN** a client posts to `/sessions`
- **THEN** the response status is `201` and `session_id` is a dashed UUID4 string
- **AND** no LLM provider is called

#### Scenario: Every session busy
- **WHEN** the store holds `MAX_SESSIONS` sessions, each with a turn in flight, and a client posts to `/sessions`
- **THEN** the response status is `503` with error code `sessions_full`

### Requirement: Session view
The system SHALL expose `GET /sessions/{session_id}` returning, without calling any LLM provider, `session_id`, `project_metadata` (see `Project metadata`), `history_turns` (the pairs in the window), `max_turns` (the configured `MAX_TURNS`), and `prompt_version`, the version the session's turns are rendered with. An unknown, expired or evicted session SHALL be answered `404` with error code `session_not_found`.

#### Scenario: Session reported
- **WHEN** a client reads a session after one completed turn
- **THEN** `history_turns` is 1, `max_turns` is the configured `MAX_TURNS`, and `prompt_version` is `v3`

#### Scenario: Unknown session
- **WHEN** a client reads `/sessions/<an id the store never issued>`
- **THEN** the response status is `404` with error code `session_not_found`

### Requirement: Session turn endpoint
The system SHALL expose `POST /sessions/{session_id}/estimate`, accepting a `multipart/form-data` body with:
- `transcript` (required): this turn's meeting transcription
- `project_type`, `detail_level`, `output_format` (required): the values of the single-shot request (see `estimation-api`)
- `output_language` (optional): at most 40 characters after stripping; an empty value means not given
- `attachments` (optional, repeatable): up to `ATTACHMENT_MAX_FILES` files (see `Attachments`); file inputs without a name or without content are ignored

It SHALL respond `200` with the single-shot response body (see `estimation-api`) plus `session_id`, `project_metadata` (the merged facts after this turn), `metadata_changes` (the names of the metadata fields this turn changed, in field order), and `history_turns` (the pairs in the window after this turn). Its `prompt_version` SHALL be the session's version (see `Session prompt version`). The endpoint SHALL have no `prompt_version` or `refresh` parameter: a turn's version and its cache behaviour are fixed.

#### Scenario: Two turns build on each other
- **WHEN** a session's first turn returns technologies `["Stripe"]` and its second returns `["Twilio"]` for the same project name
- **THEN** the second response's `project_metadata.mentioned_technologies` is `["Stripe", "Twilio"]` and `metadata_changes` is `["mentioned_technologies"]`
- **AND** the second provider call carries the first turn as a user and an assistant message before the new user message

#### Scenario: Attachment changes the estimate
- **WHEN** two sessions send the same transcript and only the second attaches `tests/fixtures/attachments/spec.pdf`
- **THEN** only the second provider call contains the PDF's text, after a `--- attachment: spec.pdf ---` line

#### Scenario: Empty file input ignored
- **WHEN** a turn's form carries an `attachments` part with no filename and no content
- **THEN** the turn is estimated as if no file had been sent

### Requirement: Streaming session turn
The system SHALL expose `POST /sessions/{session_id}/estimate/stream`, which accepts the same form as the blocking turn and streams the events of the single-shot streaming endpoint (see `Streaming estimate endpoint` in `estimation-api`), except that `result` carries the turn response and no `cache_hit` status is sent. Every check of `Turn validation and errors` SHALL complete before the stream starts, so those failures are ordinary JSON responses. A session lost after the checks SHALL end the stream with an `error` event: `session_busy` with `retryable` true when another turn took it, `session_not_found` with `retryable` false when it was evicted. The session SHALL change only when its `result` is produced (see `Turn atomicity and concurrency`).

#### Scenario: Streamed turn
- **WHEN** a client streams a valid turn
- **THEN** `partial` events precede one `result` that carries `session_id`, `project_metadata`, `metadata_changes`, and `history_turns`

#### Scenario: Busy session answered before the stream
- **WHEN** a client streams a turn while another turn of the same session is in flight
- **THEN** the response status is `409` with a JSON body whose error code is `session_busy`

#### Scenario: Session lost after the checks
- **WHEN** a session passes the checks and is then evicted before its turn takes it
- **THEN** the stream ends with an `error` event with code `session_not_found` and `retryable` false

### Requirement: Turn validation and errors
The system SHALL check every turn before calling any LLM provider, answering failures with the API's JSON error body (see `Upstream failure mapping` in `estimation-api`) except the `413`:

| Condition | Status | `error.code` |
|---|---|---|
| Unknown, expired or evicted session | 404 | `session_not_found` |
| Another turn of the same session in flight | 409 | `session_busy` |
| Missing or invalid field, blank transcript, or a transcript longer than `MAX_TRANSCRIPTION_CHARS` (the single-shot limit) | 422 | `invalid_request` |
| An attachment that is unsupported, unreadable, password-protected, larger than `ATTACHMENT_MAX_BYTES`, over the page budget, without extractable text, too slow to read, or one more than `ATTACHMENT_MAX_FILES` | 422 | `invalid_attachment`, with a message naming the sanitised file |
| No free attachment reader within `ATTACHMENT_TIMEOUT_SECONDS` | 503 | `attachments_busy` |
| A body larger than `ATTACHMENT_MAX_FILES` × `ATTACHMENT_MAX_BYTES` + 1 MiB | 413 | none: a plain-text body (see `Request body limit` in `estimation-api`) |

The transcript length, the attachment count and each attachment's size SHALL be checked before any attachment is parsed. The busy check SHALL run again after extraction, since extraction can take seconds. Provider failures SHALL follow the single-shot mapping. The API contract SHALL document each of these responses for both turn endpoints.

#### Scenario: Unsupported attachment
- **WHEN** a turn attaches a Windows executable named `spec.pdf`
- **THEN** the response status is `422` with error code `invalid_attachment` and a message naming `spec.pdf`
- **AND** no LLM provider call is made

#### Scenario: Transcript limit shared with single-shot
- **WHEN** a turn's transcript is longer than `MAX_TRANSCRIPTION_CHARS` and it attaches a file
- **THEN** the response status is `422` with error code `invalid_request`, and the attachment is never parsed

#### Scenario: No free reader
- **WHEN** every attachment reader stays busy for `ATTACHMENT_TIMEOUT_SECONDS`
- **THEN** the response status is `503` with error code `attachments_busy`

#### Scenario: Body over the upload limit
- **WHEN** a turn's body is larger than `ATTACHMENT_MAX_FILES` × `ATTACHMENT_MAX_BYTES` + 1 MiB
- **THEN** the response status is `413`

### Requirement: Conversation history
Each session SHALL keep its history as a sliding window of turns, a turn being one user message and one assistant message. The window SHALL keep the last `MAX_TURNS` pairs and SHALL then drop the oldest pairs while the window holds more than `MAX_HISTORY_CHARS` characters, never dropping the latest pair, however large. A pair SHALL count the longer of its user message and its raw client text (see `Grounding in a conversation`) plus its assistant message, so the cap bounds both what the model is sent and what the session holds. The user message kept SHALL be the rendered user message of the turn (transcript and attachments); the assistant message kept SHALL be a compact rendering of the answer, one line per fact: project name, summary, each task with its phase and likely hours, totals with the team size, and open questions. `to_messages_list(system)` SHALL return the system message first, then the pairs oldest first; a turn SHALL send the provider its system prompt, the window, and the new user message.

#### Scenario: Window bounded by turns
- **WHEN** a session with `MAX_TURNS=6` completes eight turns
- **THEN** no provider call carried more than six earlier pairs, and the last response reports `history_turns` 6

#### Scenario: One huge turn
- **WHEN** a turn's user message alone is longer than `MAX_HISTORY_CHARS`
- **THEN** the window keeps only that latest pair

#### Scenario: System message first
- **WHEN** `to_messages_list(system)` is called on a window of two pairs
- **THEN** it returns the system message, then user, assistant, user, assistant in turn order

### Requirement: Project metadata
Each session SHALL keep `project_metadata` with `project_name`, `assumed_team_size`, `mentioned_technologies`, and `agreed_scope`, derived in code from each turn's structured output (no pattern matching over text and no second LLM call) and merged after every turn:
- the latest non-blank project name (at most 120 characters) and summary (at most 1,000 characters) replace the known ones; a blank or longer value is dropped whole and the known value stays
- the team size is the sum of the latest answer's team counts; an empty team keeps the known size
- the technologies are a case-insensitive union of every turn's `technologies` that keeps the first spelling, drops names longer than 80 characters, and holds at most 30 names; once full, the known names stay and new ones are dropped without being reported as a change

The merged metadata SHALL be rendered into the next turn's system prompt as data (see `prompt-context`). The union never removes a name, so a technology the model wrongly lists stays for the rest of the session.

#### Scenario: Blank answers never erase facts
- **WHEN** a turn returns a blank project name and an empty team after the session learned both
- **THEN** the known project name and team size stay and `metadata_changes` names neither

#### Scenario: Union keeps the first spelling
- **WHEN** one turn returns `["Stripe"]` and a later one `["stripe", "Twilio"]`
- **THEN** `mentioned_technologies` is `["Stripe", "Twilio"]`

#### Scenario: Over-long values dropped
- **WHEN** a turn returns a project name of 121 characters or a technology name of 81 characters
- **THEN** that value is not stored and the known values stay

### Requirement: Turn atomicity and concurrency
Each session SHALL serialise its turns: a turn that arrives while another turn of the same session is in flight SHALL be refused with `409` `session_busy`, never queued or interleaved. A turn SHALL change the session (history pair and metadata) only once its final response exists, all at once; a failed turn, or a stream closed or cancelled before its `result`, SHALL leave the session as it was. A client that leaves a streamed turn, including one that stopped reading, SHALL release the session within about one second, so its next turn is not refused.

#### Scenario: Concurrent turns
- **WHEN** two turns of one session are sent at the same time
- **THEN** one is estimated and the other gets `409` with error code `session_busy`
- **AND** the history gains exactly one pair

#### Scenario: Client leaves mid-stream
- **WHEN** a client disconnects from a streamed turn after its first `partial` event
- **THEN** the session's next turn is answered `200` and reports `history_turns` 1

#### Scenario: Failed turn
- **WHEN** the provider is unavailable for a turn
- **THEN** the session's history and metadata are unchanged

### Requirement: Session store lifecycle
Sessions SHALL live in process memory, behind a store interface (create a session; get one by id) that a shared store can replace; they are lost on restart and not shared between worker processes. A session idle for longer than `SESSION_TTL_SECONDS` since its last use SHALL expire, and every read of a session SHALL count as a use. The store SHALL hold at most `MAX_SESSIONS` sessions; at the cap, creating a session SHALL evict, in this order, an expired session, else the least recently used session with no turns, else the least recently used session without a turn in flight. A session with a turn in flight SHALL never be evicted; when every session has one, creation SHALL fail with `sessions_full`. An expired or evicted session SHALL be answered `404` `session_not_found`, and the client recovers by creating a new session.

#### Scenario: Idle session expires
- **WHEN** a session is not used for longer than `SESSION_TTL_SECONDS`
- **THEN** reading it or sending it a turn is answered `404` with error code `session_not_found`

#### Scenario: A flood of creates spares conversations
- **WHEN** the store is at its cap, holds no expired session and at least one session with no turns, and a client creates a session
- **THEN** the least recently used session with no turns is evicted and every session with turns stays

#### Scenario: Expired before empty
- **WHEN** the store is at its cap and holds an expired session and a live empty one
- **THEN** creating a session evicts the expired one

### Requirement: Attachments
The system SHALL accept PDF, DOCX and plain-text attachments, detecting the kind from the file's bytes, never from its name, extension or declared content type: a PDF starts with `%PDF-`, a DOCX is a ZIP archive containing `word/document.xml`, and plain text is UTF-8 without NUL bytes; anything else SHALL be rejected as unsupported. Text SHALL be extracted locally with `pypdf` and `python-docx` (PyMuPDF is excluded by its AGPL licence), within these per-turn budgets:
- at most `ATTACHMENT_MAX_FILES` files of at most `ATTACHMENT_MAX_BYTES` each
- at most `ATTACHMENT_MAX_PAGES` PDF pages across the turn's files; more is rejected
- at most `ATTACHMENT_MAX_CHARS` characters across the turn's files; text past the budget is cut and marked `[truncated]`
- a DOCX whose declared uncompressed size exceeds `ATTACHMENT_MAX_DOCX_UNCOMPRESSED`, whose members are not stored or deflated, or that holds too many XML elements is rejected, and its members are inflated in bounded chunks

Password-protected PDFs, unreadable files and files without extractable text SHALL be rejected with a message naming the file. File names SHALL be sanitised (printable characters only, no `<` or `>`, at most 120 characters). Each attachment's text SHALL join the turn's user message inside the transcript block, after the transcript, introduced by a `--- attachment: <filename> ---` line, and SHALL be neutralised like the transcript (see `prompt-context`).

#### Scenario: ZIP that is not a DOCX
- **WHEN** a turn attaches a ZIP archive without `word/document.xml` named `spec.docx`
- **THEN** the response status is `422` with error code `invalid_attachment`

#### Scenario: Encrypted PDF
- **WHEN** a turn attaches a password-protected PDF
- **THEN** the response status is `422` with a message that names the file and says password-protected PDFs are not supported

#### Scenario: DOCX zip bomb
- **WHEN** a turn attaches a DOCX whose declared uncompressed size exceeds `ATTACHMENT_MAX_DOCX_UNCOMPRESSED`
- **THEN** the response status is `422` with error code `invalid_attachment` and the worker keeps serving

#### Scenario: Character budget shared
- **WHEN** a turn's attachments hold more text than `ATTACHMENT_MAX_CHARS` in total
- **THEN** the text past the budget is cut, and every attachment that lost text ends with `[truncated]`

#### Scenario: Attachment text is data
- **WHEN** an attachment's text contains `</transcript>` and "ignore previous instructions"
- **THEN** the user message still contains exactly one `</transcript>`, the prompt's own

### Requirement: Attachment isolation
Attachment text SHALL be extracted in a short-lived child process, so a hostile file can at worst take down that process. The child SHALL be killed after `ATTACHMENT_TIMEOUT_SECONDS` (the file is then rejected as too slow to read), SHALL have its address space capped at `ATTACHMENT_MAX_MEMORY_BYTES` where the operating system enforces it (Linux), and SHALL have a CPU-time limit one second above the timeout as a backstop. A child that dies, runs out of memory, or crashes SHALL make the turn fail with `422` `invalid_attachment`, never crash the worker. At most `ATTACHMENT_MAX_CONCURRENT` children SHALL run at once per process; a turn SHALL wait up to `ATTACHMENT_TIMEOUT_SECONDS` for a free one and then fail with `503` `attachments_busy`. A rejection SHALL log its reason only, never the document's text, a parser's message, or a traceback.

#### Scenario: Slow file killed
- **WHEN** a file keeps its reader busy past `ATTACHMENT_TIMEOUT_SECONDS`
- **THEN** the child is killed and the turn fails with `422` and a message that names the file and says it took too long to read

#### Scenario: Readers bounded
- **WHEN** `ATTACHMENT_MAX_CONCURRENT` is 1 and a second extraction starts while the first runs
- **THEN** the second waits for the slot, and fails with `attachments_busy` only if none frees up within the timeout

#### Scenario: Rejection logged without content
- **WHEN** an attachment fails to parse
- **THEN** the log records carry the reason and the exception type, and none contains the document's text

### Requirement: Grounding in a conversation
A turn's grounding report (see `Grounding verification` in `prompt-context`) SHALL check evidence against the raw client text the model saw, not neutralised, current turn first: this turn's transcript and the attachments its prompt version shows, then the transcripts and attachments of the turns still in the window. It SHALL never use the prompt's own wording, the project metadata or the assistant messages. Each pair SHALL keep its turn's raw client text and drop it when it leaves the window, so a quote from a turn that slid out is ungrounded.

#### Scenario: Quote from an earlier turn
- **WHEN** turn 3 quotes "must work offline" from turn 1 and turn 1 is still in the window
- **THEN** the requirement is grounded

#### Scenario: Quote from a turn that slid out
- **WHEN** the same quote arrives with `MAX_TURNS=1`, after turn 1 left the window
- **THEN** the requirement is listed in `grounding.ungrounded_requirement_ids`

#### Scenario: Quote from an attachment
- **WHEN** a requirement's evidence appears only in the turn's attached PDF
- **THEN** the requirement is grounded

### Requirement: Session prompt version
Session turns SHALL be rendered with `estimation/v3`, the conversation service's version, whatever `PROMPT_VERSION` says; no setting or request parameter SHALL change it. The single-shot endpoints SHALL keep `PROMPT_VERSION` (see `estimation-api`). Every turn response and `GET /sessions/{session_id}` SHALL report the version.

#### Scenario: Version independent of the setting
- **WHEN** the service runs with `PROMPT_VERSION=v2` and a session completes a turn
- **THEN** the turn's prompt is rendered from `v3` and its response reports `prompt_version` `v3`
- **AND** a single-shot request without `prompt_version` is still rendered from `v2`

### Requirement: Turns bypass the response cache
Session turns SHALL never read or write the response cache, since the same message means something else in another conversation; each turn's `llm_call` record SHALL report cache status `bypass` (see `response-cache`).

#### Scenario: Repeated turn reaches the provider
- **WHEN** two sessions send the same first turn with a response cache configured
- **THEN** the provider is called for both, the cache is neither read nor written, and both `llm_call` records report cache status `bypass`
