# Agent Guide

Spec-driven FastAPI project for the LIDR AI Engineering course. Each course brief is a milestone, delivered as a reviewable branch.

## Ground rules
- English only: code, docs, specs, commits.
- Specs first. Behavior lives in `openspec/specs/` (current truth) and `openspec/changes/<change>/` (in-flight deltas). If code and plan disagree, fix the plan first, then the code.
- Verify library/SDK usage with Context7 before writing integration code; do not rely on memory.
- Tests never call real LLM APIs. Live checks go through `make eval`.
- Comply or explain: deviations from `openspec/config.yaml` rules are recorded in the change's `design.md`.

## Workflow
1. `/opsx:explore` - think through an idea (optional).
2. `/opsx:propose` (or `/opsx:new` + `/opsx:continue`, or `/opsx:ff`) - create the change artifacts.
3. `/opsx:apply` - implement `tasks.md` test-first; one conventional commit per task group; `make check` green before each commit.
4. `/opsx:verify` - check implementation against specs and scenarios.
5. `/opsx:archive` - fold spec deltas into `openspec/specs/` after review.

## Commands
| Command | Purpose |
|---|---|
| `make check` | Everything CI runs: lint, types, tests, spec validation |
| `make specs` | `openspec validate --all --strict` + archived-change check |
| `make eval` | Live prompt evaluation against the golden set (needs API keys) |
| `make openspec-sync` | Regenerate `/opsx:*` workflows from the repo-scoped profile in `.openspec/` |

## Branches
One branch per milestone (e.g. `feat/m1-cag-estimator`); merge to `main` and tag (`m1`) after review. Never force-push.
