# Handoff: autonomous implementation of the catch-up

You are the **orchestrator** for an unattended overnight run. Read, in this order: `docs/catch-up/spec.md` → this file → the plan of the current branch (`docs/catch-up/plan-session-0N.md`) → `docs/catch-up/PROGRESS.md` → `.claude/stack.md` → `AGENTS.md`. Then continue from the first unchecked task in `PROGRESS.md`.

## Owner decisions (2026-10-06, binding)

- Scope, design and plans: approved; the owner explicitly **waived reviewing the written spec and plans** before implementation. Implement them; if the code proves a plan wrong, fix the plan file first (one-line note in `PROGRESS.md`), then the code.
- **Multi-agent orchestration is approved:** subagents (Agent tool) for every task and review, parallel git worktrees for the two tracks, and the **Workflow tool** for the end-of-branch review panel (≤ 8 agents per workflow).
- **Push is approved** for `pre-session-03`, `pre-session-04`, `pre-session-05` (use `GH_TOKEN=$(gh auth token --user ethx42)` for `git push` / `gh`). **No pull requests. No emails** (the owner sends the links). Never push `main`.
- **Live LLM spend:** ≤ US$5 in total, only through the guarded make targets; models `gpt-4o-mini` and `claude-haiku-4-5` only. API keys are in `.env` (never read or print it).
- Defaults accepted: primary `openai:gpt-4o-mini`, fallback `anthropic:claude-haiku-4-5`; notify the owner's phone only for a pushed branch or a blocker; leave a morning report.

## Priorities

The AI service is the product core and must be top tier; the web client must be enterprise-grade (spec §8) but comes second. If time runs short, finish in this order: S3 AI → S3 web → S4 AI → S4 web → S5 AI → S5 web → polish. Within each branch build the thin end-to-end slice first (each plan lists its execution order), then deepen. The session 5 live class is on 2026-10-07; a partial `pre-session-05` pushed is better than none, as long as everything pushed is green.

## Branch flow

```bash
git switch pre-session-03            # already exists, contains docs/catch-up
# ... after GATE PASS pre-session-03:
git switch -c pre-session-04         # from the final pre-session-03 commit
# ... after GATE PASS pre-session-04:
git switch -c pre-session-05
```

Never rebase or force-push a pushed branch. Fixes to an earlier branch after it was pushed are not needed tonight; note them in `PROGRESS.md` instead.

## Per-branch protocol

0. **Pre-flight (once per branch, print the outputs):** `git status --short` (clean), `git branch --show-current`, `docker info --format '{{.ServerVersion}}'`, `uv --version`, `node --version`, `pnpm --version`, total spend so far (`uv run python -c "from scripts.live_budget import total_spent; print(total_spent())"` once Task 1 of S3 exists).
1. **Plan audit (once per branch):** one fresh subagent (most capable model) reads the branch plan, `spec.md` and the brief PDF (`pdftotext -layout "<pdf>" -` works; paths in the plan header) and reports concrete gaps: brief checklist items with no task, interface names that disagree between tasks, steps that cannot work as written. Fix the plan file before executing. Record "plan audited" in `PROGRESS.md`.
2. **Tasks:** follow `superpowers:subagent-driven-development`. Per task: an implementer subagent (TDD, gets the full task text, the Global Constraints and Review Focus of the plan, and the relevant `.claude/stack.md` sections), then a spec-compliance reviewer, then a code-quality reviewer; fixes loop until both approve. Use the most capable model for AI-service tasks and all reviews; a faster model is acceptable for scaffolding and docs. The orchestrator runs `make check`, commits (one conventional commit per task), ticks the task in `PROGRESS.md` with the short SHA, and prints the last lines of `make check`.
3. **Parallel tracks:** after the slice tasks of a branch are committed, create two worktrees with `superpowers:using-git-worktrees` (e.g. `../lidr-ai-eng-wt/s03-ai` on `pre-session-03-ai`, `../lidr-ai-eng-wt/s03-web` on `pre-session-03-web`, both from the slice commit). Run the AI track and the web track concurrently (one subagent chain each). Merge each back into `pre-session-0N` with `git merge --no-ff`; on conflicts in generated files, regenerate (`make openapi`, `make web-types`) rather than hand-merging. Delete the temporary branches and worktrees afterwards (local only; never push them).
4. **Gates:** the branch is done only when `make gate BRANCH=pre-session-0N` prints `GATE PASS pre-session-0N <sha>` for the commit on `origin`.
5. **Review panel (before the gate):** a Workflow script with parallel reviewers — AI-service correctness; streaming, cancellation and concurrency; security (prompt injection, uploads, secrets, BFF forwarding, SSRF, logs without PII); UI, accessibility and visual hierarchy (`gsd-ui-review` style audit using the Playwright screenshots) — followed by an adversarial verifier per finding. Confirmed findings become fix tasks (failing test first). Record findings and outcomes in `PROGRESS.md`.
6. **Close-out:** takeaways + quiz (`humanizer` pass), specs updated in place, README updated, push, gate, PushNotification.

## Rules every agent follows (reviewers reject diffs that break them)

- Never delete, skip, xfail or weaken a test to get green. Never lower a gate threshold.
- No `# type: ignore`, `Any`, `as any`, `@ts-expect-error` or lint disables without a one-line justification on the same line.
- Never read, print, log or commit `.env` or secrets. Never log transcripts or attachment text.
- Generated files (`contracts/openapi.json`, `web/src/lib/ai-service/schema.d.ts`) are only changed by their generators.
- Tests never call real LLMs. Live calls only via `make smoke-live`, `make record-cassettes`, `make eval`, `make smoke-live-session` (spend-guarded).
- Verify library usage against `.claude/stack.md`; when it lacks something, use Context7 and the installed package, then add what you learned to the brief.
- Never commit to `main`, never force-push, never `git reset --hard`, never `rm -rf`.

## Evidence for the `/goal` evaluator

The goal evaluator only sees this conversation. At the end of every branch, print in the transcript: the tail of `make check`, the `docker compose up --build --wait` result, the Playwright summary line, the `GATE PASS …` line, `git log -1 --oneline origin/<branch>`, and `cat docs/catch-up/PROGRESS.md`. When stopping for any reason, print `cat docs/catch-up/PROGRESS.md` last.

## Failure policy

A task that still fails after 3 fix attempts is marked `blocked` in `PROGRESS.md` with the failing command, the last error lines and what was tried. Continue with tasks that do not depend on it. If the block prevents a gate, stop that branch, send a PushNotification ("blocked: <task> — <one-line reason>"), and continue with the next independent work only if it does not build on the blocked branch. Never paper over a failure.

## Context hygiene

Delegate file-heavy work to subagents and keep only their summaries. Do not read large files or logs whole; grep or tail. Auto-compaction may summarise this conversation: `PROGRESS.md` and git history are the source of truth, so re-read them after any compaction or resume.

## Morning report

After the last branch (or when stopping), publish one private Artifact titled "Catch-up report" (load the `artifact-design` skill first): per branch — gate line, commit, link `https://github.com/ethx42/lidr-ai-eng/tree/<branch>`, what was built, eval and smoke numbers, review findings and fixes, blocked items, spend; links to each `docs/takeaways/session-0N.md` on GitHub; key screenshots. Send a final PushNotification with the report link.
