# Catch-up progress

Source of truth for the overnight run. Tick a task only after its commit exists; put the short SHA after it. Blocked tasks: replace `[ ]` with `[!]` and add a line below with the command, the last error lines and what was tried.

Spend ledger: `docs/catch-up/spend.jsonl` (budget US$5). Spent so far: US$0.048279

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
- [ ] Task 18: End-to-end tests, accessibility and media
- [ ] Task 19: CI
- [ ] Task 20: Branch close-out
- [ ] Review panel findings resolved
- Gate:

## pre-session-04

- [x] Plan audited (early, ~40 plan defects fixed; rulings in Notes)
- [ ] Task 1: Typed request contract
- [ ] Task 2: Jinja2 prompt loader and estimation/v1
- [ ] Task 3: Context endpoint and cache isolation for typed params
- [ ] Task 4: prompt_version query parameter
- [ ] Task 5: Output-format layouts in the markdown renderer
- [ ] Task 6: Prompt v2 and the comparison eval
- [ ] Task 7: Web — typed form workspace with evidence-linked split view
- [ ] Task 8: E2E, accessibility and media
- [ ] Task 9: Branch close-out
- [ ] Review panel findings resolved
- Gate:

## pre-session-05

- [x] Plan audited (early, 30 plan defects fixed; rulings in Notes)
- [ ] Task 1: Messages-based provider interface
- [ ] Task 2: Session state — app/sessions.py
- [ ] Task 3: Output schema technologies and the metadata merge
- [ ] Task 4: Attachment extraction (path B)
- [ ] Task 5: Prompt estimation/v3 with project metadata and attachments
- [ ] Task 6: Conversation service
- [ ] Task 7: Session endpoints and the brief's integration tests
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

- PAUSED 2026-10-07 (usage limit). Worktrees: `../lidr-ai-eng-wt/s03-ai` (branch `pre-session-03-ai`, Tasks 12–14 done, head af9a0a2) and `../lidr-ai-eng-wt/s03-web` (branch `pre-session-03-web`, Tasks 6–9 done at de272e3; Task 10 implementer may have committed after that, unreviewed). Resume: review Task 10, then Task 11 (web) and Tasks 15–16 (AI), merge both tracks with `--no-ff`, `make openapi && make web-types`, then Tasks 17–20. Orchestrator ledger: `.superpowers/sdd/plan-session-03/progress.md`. Live spend so far: US$0.004369 (in the AI worktree's `spend.jsonl`).
- Owner action: `.env.example` writes are blocked by the permission rule on `.env*`, so its `REPLAY_*` and `LIVE_BUDGET_USD` documentation is pending. Proposed content: `.superpowers/sdd/plan-session-03/env-example.proposed` (apply with `cp .superpowers/sdd/plan-session-03/env-example.proposed .env.example`, then commit `docs(env): document replay and live budget settings`).
