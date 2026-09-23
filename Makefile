OPENSPEC_VERSION := 1.13.1
OPENSPEC := npx -y @fission-ai/openspec@$(OPENSPEC_VERSION)

.PHONY: specs openspec-sync

# Validate active changes, main specs, and that archived changes have no open tasks
specs:
	$(OPENSPEC) validate --all --strict --no-interactive
	$(OPENSPEC) validate --archived --no-interactive

# Regenerate OpenSpec agent workflows from the repo-scoped profile (.openspec/), leaving the global config untouched
openspec-sync:
	OPENSPEC_TELEMETRY=0 XDG_CONFIG_HOME=$(CURDIR)/.openspec $(OPENSPEC) update --force
