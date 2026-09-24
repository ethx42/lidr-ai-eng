OPENSPEC_VERSION := 1.13.1
OPENSPEC := npx -y @fission-ai/openspec@$(OPENSPEC_VERSION)
REPORT ?=

.PHONY: install run test lint typecheck specs check eval eval-baseline openspec-sync

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

# Validate active changes, main specs, and that archived changes have no open tasks
specs:
	$(OPENSPEC) validate --all --strict --no-interactive
	$(OPENSPEC) validate --archived --no-interactive

# Same checks, same order as CI
check: lint typecheck test specs

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
