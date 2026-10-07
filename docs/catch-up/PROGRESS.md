# Catch-up progress

Source of truth for the overnight run. Tick a task only after its commit exists; put the short SHA after it. Blocked tasks: replace `[ ]` with `[!]` and add a line below with the command, the last error lines and what was tried.

Spend ledger: `docs/catch-up/spend.jsonl` (budget US$5). Spent so far: US$0.00

## pre-session-03

- [x] Plan audited (51 plan defects fixed; rulings in Notes)
- [ ] Task 1: Bootstrap — gate, spend guard, agent guide
- [ ] Task 2: Streaming contract, pricing and call metrics
- [ ] Task 3: Partial snapshots from streamed JSON
- [ ] Task 4: Replay provider
- [ ] Task 5: Streaming service, SSE endpoint and context endpoint
- [ ] Task 6: Web scaffold, design tokens and typed client
- [ ] Task 7: BFF route handlers
- [ ] Task 8: useEstimateStream hook
- [ ] Task 9: Estimate view (progressive rendering)
- [ ] Task 10: Chat page
- [ ] Task 11: Inspector panel
- [ ] Task 12: OpenAI streaming
- [ ] Task 13: Anthropic streaming and mid-stream error mapping
- [ ] Task 14: Fallback router with cooldown
- [ ] Task 15: Exact-match response cache
- [ ] Task 16: Cassette recorder and live smoke test
- [ ] Task 17: Docker and Compose
- [ ] Task 18: End-to-end tests, accessibility and media
- [ ] Task 19: CI
- [ ] Task 20: Branch close-out
- [ ] Review panel findings resolved
- Gate:

## pre-session-04

- [ ] Plan audited
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

- [ ] Plan audited
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

