OPENSPEC_VERSION := 1.13.1
OPENSPEC := npx -y @fission-ai/openspec@$(OPENSPEC_VERSION)
REPORT ?=

.PHONY: install run test lint typecheck specs check eval eval-baseline openspec-sync gate

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest -q

lint:
	uv run ruff check --no-cache .
	uv run ruff format --no-cache --check .

typecheck:
	uv run mypy

# Validate active changes, main specs, and that archived changes have no open tasks
specs:
	$(OPENSPEC) validate --all --strict --no-interactive
	$(OPENSPEC) validate --archived --no-interactive

# Same checks, same order as CI
check: lint typecheck test specs web-check

.PHONY: web-install web-types web-check
web-install:
	pnpm -C web install --frozen-lockfile

# Regenerate web/src/lib/ai-service/schema.d.ts from contracts/openapi.json
web-types:
	pnpm -C web gen:types

web-check:
	pnpm -C web lint
	pnpm -C web typecheck
	pnpm -C web test
	pnpm -C web check:types

# Live prompt evaluation against the golden set (needs API keys; never part of `check`)
eval:
	uv run python -m evals.run_eval $(if $(REPORT),--report $(REPORT))

# Record a completed eval report as the committed baseline: make eval-baseline [REPORT=path]
eval-baseline:
	@src="$(REPORT)"; [ -n "$$src" ] || src=$$(ls -t evals/reports/*.json 2>/dev/null | head -1); \
	[ -n "$$src" ] || { echo "No eval report found; run 'make eval' first" >&2; exit 1; }; \
	cp "$$src" evals/baseline.json && echo "Baseline <- $$src"

# Regenerate OpenSpec agent workflows from the repo-scoped profile (.openspec/), leaving the global config untouched
openspec-sync:
	OPENSPEC_TELEMETRY=0 XDG_CONFIG_HOME=$(CURDIR)/.openspec $(OPENSPEC) update --force

# Branch close gate (see docs/catch-up/): make gate BRANCH=pre-session-03
gate:
	bash scripts/gate.sh $(BRANCH)

# Regenerate the committed API contract (contracts/openapi.json); `make check` fails when stale
.PHONY: openapi
openapi:
	uv run python -m scripts.export_openapi

# Live, budget-guarded recordings (scripts/live_budget.py): replay cassettes for the UI's sample
# transcripts into tests/cassettes/, or with SSE=<provider> a raw SSE fixture into
# tests/fixtures/sse/<provider>/: make record-cassettes [SSE=openai|anthropic]
.PHONY: record-cassettes
record-cassettes:
	uv run python -m $(if $(SSE),scripts.record_sse_fixture $(SSE),scripts.record_cassettes)

# Live, budget-guarded: one streamed estimate per provider and a forced fallback (exit 1 on failure)
.PHONY: smoke-live
smoke-live:
	uv run python -m scripts.smoke_live

# Docker Compose: the production-like stack (web on http://localhost:3000 only; waits for every
# healthcheck), the dev stack with reload and watch (AI service also on :8000), teardown and logs
.PHONY: up dev down logs
up:
	docker compose up --build --wait

dev:
	docker compose -f compose.yaml -f compose.dev.yaml up --build --watch

down:
	docker compose down

logs:
	docker compose logs -f
