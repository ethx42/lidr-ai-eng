# Catch-up progress

Source of truth for the overnight run. Tick a task only after its commit exists; put the short SHA after it. Blocked tasks: replace `[ ]` with `[!]` and add a line below with the command, the last error lines and what was tried.

Spend ledger: `docs/catch-up/spend.jsonl` (budget US$5). Spent so far: US$0.088722 (S3 US$0.048279, S4 US$0.040443)

## pre-session-03

- [x] Plan audited (51 plan defects fixed; rulings in Notes)
- [x] Task 1: Bootstrap — gate, spend guard, agent guide (1f2e518)
- [x] Task 2: Streaming contract, pricing and call metrics (ebac836)
- [x] Task 3: Partial snapshots from streamed JSON (a1df623)
- [x] Task 4: Replay provider (9103f21)
- [x] Task 5: Streaming service, SSE endpoint and context endpoint (e159973, 92dbe31)
- [x] Task 6: Web scaffold, design tokens and typed client (1c76f90)
- [x] Task 7: BFF route handlers (9ad502a)
- [x] Task 8: useEstimateStream hook (e918f9b)
- [x] Task 9: Estimate view (progressive rendering) (de272e3)
- [x] Task 10: Chat page (504dd10)
- [x] Task 11: Inspector panel (f2cd253)
- [x] Task 12: OpenAI streaming (95f9454)
- [x] Task 13: Anthropic streaming and mid-stream error mapping (780db0c)
- [x] Task 14: Fallback router with cooldown (af9a0a2)
- [x] Task 15: Exact-match response cache (e23222f)
- [x] Task 16: Cassette recorder and live smoke test (97ecb2b, d78d6a4, 74cfd38)
- [x] Task 17: Docker and Compose (6667c42, 9bf9744, 86c246f)
- [x] Task 18: End-to-end tests, accessibility and media (724905e)
- [x] Task 19: CI (e66aade)
- [x] Task 20: Branch close-out (7e8260b, 2ce0c49, 2a18ccd)
- [x] Review panel findings resolved (10 confirmed fixed: AI 5a1e64d, web 9b1f700, final 0b6a5d1)
- Gate: GATE PASS pre-session-03 9af03a1de94dc7d7da7d0b854c8911f2e130105b (2026-10-07; recorded on pre-session-04 so the gated commit stays untouched)

## pre-session-04

- [x] Plan audited (early, ~40 plan defects fixed; rulings in Notes)
- [x] Task 1: Typed request contract (cef6ad0)
- [x] Task 2: Jinja2 prompt loader and estimation/v1 (9552574)
- [x] Task 3: Context endpoint and cache isolation for typed params (5a4e043)
- [x] Task 4: prompt_version query parameter (f5c4ba2)
- [x] Task 5: Output-format layouts in the markdown renderer (bee99a6)
- [x] Task 6: Prompt v2 and the comparison eval (51f550b)
- [x] Task 7: Web — typed form workspace with evidence-linked split view (25cf774)
- [x] Task 8: E2E, accessibility and media (207e3d9, 8b79b92, 8e5b6e0, 31874f6, c7381f6)
- [x] Task 9: Branch close-out (104e9a2, 4b00916, 7ab7829, 914c43a)
- [x] Review panel findings resolved (12 found, 11 confirmed, 1 refuted; 9 fixed: AI 867fcca, 4a0280e, 914c43a; web 7dcc9a2..108ccc3 merged in a225dbe; 2 deferred into S5 Task 5: ai-1, ai-2)
- Gate:

## pre-session-05

- [x] Plan audited (early, 30 plan defects fixed; rulings in Notes)
- [x] Task 1: Messages-based provider interface (f31da42, 5d32ab8)
- [x] Task 2: Session state — app/sessions.py (55809a8, ec26057)
- [x] Task 3: Output schema technologies and the metadata merge (e4d2443, 19c4bc0)
- [x] Task 4: Attachment extraction (path B) (413205a, 7a1d209, 8c78af9, 64c5ff6, 551aa15, e6878e1; merged 637b99c)
- [x] Task 5: Prompt estimation/v3 with project metadata and attachments (bae6464, d9047db, 45cbb2f, 112506d, 1252428)
- [x] Task 6: Conversation service (4a117d7, aa57299, 33eab70, ebe0f2a)
- [x] Task 7: Session endpoints and the brief's integration tests (7eb2340, df63522, b3c4844, ea988e8, 0b9aa48, bbb7f4b)
- [ ] Task 8: Web — session workspace
- [ ] Task 9: E2E, live check and branch close-out
- [ ] Review panel findings resolved
- Gate:

## Notes, plan corrections and findings
- S3 plan audit (2026-10-07): 51 defects fixed in `plan-session-03.md` (fixtures that did not exist, cross-track ownership of Makefile/stack.md, `LLM_FALLBACKS=none`, cache status for `cache=error` logs, e2e override, CI watch). Spec §4.1/§4.2/§4.7 wording aligned.
- Ruling: Regenerate bypasses the exact-match cache (`?refresh=true`), so it really produces a new answer.
- Ruling: the composer's limit comes from `/api/v1/context` (`max_transcription_chars`), not a hard-coded constant.
- Ruling: baseline `make check` failed because ruff 0.16 formats Python blocks inside `docs/**/*.md`; Task 1 excludes `docs` from ruff.
- Ruling: replay pacing knob is `REPLAY_DELAY_SCALE` (0 = instant, 1 = as recorded); "speed = 2" reading as slower was a trap.
- Ruling: provider `stream()` is typed `AsyncGenerator` (so callers can `aclose()` it under mypy strict); spec §4.1 updated.
- S4/S5 plans audited early (2026-10-07) against the S3/S4 plans' end states, in parallel with S3 work; re-check interfaces at each branch start.
- Ruling (S4): skip the brief's optional `reference_projects` bonus (README notes it).
- Ruling (S4): result pane gets a "Structured | Document" toggle so `output_format` has a visible effect.
- Ruling (S4): v2 becomes the default if its score ≥ v1 − 0.02 and its `covers_frontend` pass rate ≥ v1's.
- Ruling (S5): session endpoints use `estimation/v3`; single-shot keeps the S4 default; S4 evidence highlighting stays inside each turn card; e2e on synthetic replay; the replay GIF gets a caption.

- Owner action: `.env.example` writes are blocked by the permission rule on `.env*`, so its `REPLAY_*` and `LIVE_BUDGET_USD` documentation is pending. Proposed content: `.superpowers/sdd/plan-session-03/env-example.proposed` (apply with `cp .superpowers/sdd/plan-session-03/env-example.proposed .env.example`, then commit `docs(env): document replay and live budget settings`). The proposal now also documents `ALLOWED_HOSTS` (AI-service Host allowlist); once committed, trim the README sentence that says `.env.example` does not list these yet.
- Accepted deviation (Task 18): composer shortcut hint opacity raised 70→80 % to pass WCAG 1.4.3 contrast found by the axe gate.
- S3 review panel (Workflow, 4 reviewers + 4 adversarial verifiers): 17 findings, 10 confirmed (1 important: short-viewport layout collapses the thread; 9 minor: failed-call logs drop billed tokens, Anthropic mid-stream upstream_status=200, BFF Host allowlist vs DNS rebinding, eval budget bound, stale "Estimate ready" after a stopped regenerate, touch keyboard over results, hover contrast, inspector polish, toast tokens), 7 refuted. Fixes run as two parallel waves (AI, web) with a failing test first; selected deferred minors from task reviews are folded in.
- S3 paused twice on usage limits and resumed; a transient GitHub 500 on push (request E6FD:103FE5:1F85C7:24FFF0:6AC660F0) cleared after 4 retries. S4 was started in a worktree while the push retried.
- S4 plan re-checked against the real S3 code before Task 1 (cassette re-record in Task 2, `.env.example` changes as owner proposals, caller lists, web workspace replacing `chat.tsx`). Rulings: slice in a worktree; OpenAPI example uses the code-default prompt version; `CACHE_SCHEMA` bump on the layout change.
- S4 Task 8 ruling: the short-window threshold is 48.25rem (772 px), measured after a run; the 240 px bar covers the estimate pane's content. 1366x768 windows now use the page-scroll layout; e2e checks both sides of the threshold (1280x772, 1280x773).
- S4 review panel (Workflow, 4 reviewers + 4 adversarial verifiers): 12 findings, 11 confirmed (all minor after verification), 1 refuted (inactive mark contrast). Fixed: published-version pin covers every project type x detail level x output format plus user.j2, and every version must have a pin; streaming highlights mark only complete quotes; Evidence pins grounded quotes below 768 px; segmented controls check on arrow (Radix RadioGroup); equal pane header heights; Context tab keeps contrast and the last good prompt with a polite inline error and Retry; Document table region named by its heading and focusable only when it scrolls. Deferred into S5 Task 5 (v3 is the next prompt version): ai-1 the summary level's "at most eight tasks" vs the 80 h task cap; ai-2 Anthropic system prompt cached as one block.
- Known flake to watch: tests/unit/test_llm_service_cache.py first-event bound (0.25 s) exceeded once (0.259 s) while a Docker e2e ran in parallel; green on rerun, never in sequential runs.
- Owner commit on pre-session-04: 4cf1577 `.env.example` (S3+S4 settings).
- S5 plan re-checked against the real S4 code before Task 1 (40 edits; rulings S5-R1..R8 in the plan). S4 panel items ai-1 (summary vs 80 h cap) and ai-2 (Anthropic system cache blocks) carried into S5 Task 5.
- S5 Task 3 eval (measurement, ruling S5-R2): v2 after the `technologies` schema change scored 0.9231 and 0.9423 (mean 0.9327) against the 0.9415 floor; S4's v2 two-run mean was 0.9519. Baseline and floor untouched; reported in the README.
- S5 Task 4 ruling: attachments are parsed in a killable forkserver child (hard timeout, best-effort RLIMIT_AS/RLIMIT_CPU, at most ATTACHMENT_MAX_CONCURRENT children) instead of an in-thread tracer; in-process bounds (stored/deflated members only, bounded inflate, XML-tag cap, char budget, lowered pypdf caps) stay as defence in depth. Review findings fixed: bzip2/LZMA zip bomb (374 B → 631 MB), invalid ZIP names → 500, a 5.5 KB PDF burning 37 s of CPU, silent MemoryError.
- S5 Task 5: v3 also closes the S4 panel's ai-1 (the summary level keeps a medium breakdown's total and allows coarse tasks over 80 h) and ai-2 (Anthropic gets the static prefix and the variable tail as two system blocks, cache_control on the static one). Review finding fixed: model-echoed metadata in the system prompt is data (explicit rule), one line per value with < and > stripped, name and scope bounded.
- S5 Task 6 ruling: each turn is grounded against the raw client text the model saw (the transcripts and attachments of the turns still in the window, current turn first), never against prompt scaffolding or the model-derived metadata.
- S5 Task 7 ruling (after a background security review flagged session eviction as a DoS): at the session cap the store evicts expired sessions, then the least recently used session with no turns, then the least recently used idle one, never a session with a turn in flight; when every session is busy, POST /sessions answers 503 sessions_full. A flood of new sessions only churns empty ones.
