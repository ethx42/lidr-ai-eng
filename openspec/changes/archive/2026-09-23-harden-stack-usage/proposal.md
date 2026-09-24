## Why

Grounding the project against its installed stack (`.claude/stack.md`, 2026-09-23) found nine gaps between how M1 uses its SDKs and tools and how the installed versions are meant to be used. Two affect correctness or cost. OpenAI prompt caching never hits (`cached_input_tokens` is 0 on every gpt-4o-mini eval call), and the Anthropic adapter accepts output truncated by the context window. The rest are latent risks: a runtime import declared only as a dev dependency, drifting uv versions, and lint/type/test settings weaker than the tools now offer. Fixing them now, before M2 builds on this code, keeps the baseline honest.

## What Changes

- **OpenAI prompt caching**: every OpenAI request carries a stable cache routing key derived from the prompt version. Provider usage gains `cache_write_tokens` (OpenAI `cache_write_tokens`, Anthropic `cache_creation_input_tokens`), reported in the API `usage`, the per-call log record, and eval reports. OpenAI caching is re-measured with a live eval.
- **Anthropic truncation**: `stop_reason == "model_context_window_exceeded"` is treated as invalid (truncated) output, like `max_tokens`.
- **Runtime dependency**: `httpx2` (imported by the OpenAI adapter) moves from dev to runtime dependencies. `pydantic` and `starlette`, which the app also imports but only gets transitively, are declared directly as well. A test guards that every third-party import in `app/` is a direct runtime dependency.
- **uv pinning**: `[tool.uv] required-version` pins the uv range used locally and in CI, CI sets `UV_LOCKED=1`, and the local uv is upgraded to match.
- **pytest**: move to the native `[tool.pytest]` table with `strict = true` and an explicit `asyncio_default_fixture_loop_scope`.
- **ruff**: `select` becomes `extend-select` so the new default rule set applies (new findings are fixed), and the duplicate `target-version` is dropped (it is read from `requires-python`).
- **mypy**: enable `warn_unreachable`, the extra error codes (`ignore-without-code`, `redundant-expr`, `truthy-bool`, `possibly-undefined`), and the `[tool.pydantic-mypy]` strictness flags.
- **Reasoning effort**: `LLM_REASONING_EFFORT` accepts every level the installed SDKs define (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`). A level is sent only when the configured model supports it. Otherwise it is omitted and a startup warning names the model and the supported levels.
- **Polish**: single-field schema rules use `AfterValidator` (the LLM JSON schema stays unchanged); the redundant `response_model=` is dropped; dependencies use reusable `Annotated` aliases; the `Content-Type: application/json` requirement is specified and documented; the README gains a production `uvicorn --factory` command.

No breaking changes. The API `usage` object gains one field. Existing `LLM_REASONING_EFFORT` values keep their meaning.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `llm-providers`: cache routing key on OpenAI requests; `cache_write_tokens` in usage and logs; context-window truncation counts as invalid output; per-model reasoning-effort levels with omit-and-warn for unsupported levels.
- `configuration`: `LLM_REASONING_EFFORT` accepts the full set of SDK effort levels.
- `estimation-api`: `usage` includes cache write tokens; requests without a JSON content type are rejected with `422`.
- `prompt-evaluation`: token usage in reports includes cache write tokens.
- `quality-gates`: runtime imports must be runtime dependencies; the package manager version is pinned and CI never re-locks.

## Impact

- Code: `app/config.py`, `app/schemas/estimation.py`, `app/services/providers/{openai,anthropic}_provider.py`, `profiles.py`, `app/observability.py` (through `Usage`), `app/routers/estimations.py`, `evals/run_eval.py` (through `Usage`), tests.
- Config: `pyproject.toml` (deps, `[tool.uv]`, `[tool.pytest]`, ruff, mypy), `uv.lock`, `.github/workflows/ci.yml`, `README.md`, `.env.example`.
- API: additive `usage.cache_write_tokens` field. OpenAPI example updated.
- Tooling: local uv upgraded to the pinned range. CI uv follows `required-version`.

## Explicitly deferred

- **OpenAI `prompt_cache_options` (explicit breakpoints, TTL, prewarm)**: only available on gpt-5.6+; the default model is gpt-4o-mini. Revisit when the default model changes.
- **Anthropic 1-hour cache TTL and `diagnostics` cache-miss reasons**: caching already hits on Anthropic (v1 eval: ~8k of ~8.3k input tokens cached); no problem to solve yet.
- **Anthropic middleware replacing httpx hooks**: the quota-429 hook lives on the OpenAI client only; nothing to migrate on Anthropic.
- **Live effort-level discovery via the Models API**: effort support stays in the static profile table (M1 pattern). A startup API call adds latency and a failure mode for little gain at this scale.
