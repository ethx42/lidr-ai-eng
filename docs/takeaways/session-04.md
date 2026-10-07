# Session 4 takeaways: typed form, versioned prompts, and what the tests can't see

Branch `pre-session-04` replaced the session 3 chat with a typed form and moved the estimation prompt out of Python into versioned Jinja2 templates. The form sends three enums next to the transcript. The AI service renders `app/prompts/estimation/<version>/{system,user,examples}.j2` through one loader, any request can pick a version with `?prompt_version=`, and a new eval check measured whether prompt `v2` fixes a gap that M1 left open: estimates that skip frontend work for client-facing surfaces.

The brief asks you to defend four things in a technical conversation. Sections 1 to 4 answer them, one each. Sections 5 to 9 cover the rest of the session's topics. Each section explains the idea and why it exists, what it costs, what this branch did (paths, numbers, review findings), and which alternative would pay off more, and when. There's a quiz at the end.

The numbers this branch produced, all on `openai/gpt-4o-mini` over the five golden cases:

| Run | Score | `covers_frontend` |
|---|---|---|
| `v1` (Jinja port of M1 `v4`), before the check existed | 1.0 (47/47) | not measured |
| `v1`, run 1 / run 2 | 0.9231 / 0.9231 (48/52 twice) | 2/5, 1/5 |
| `v2`, run 1 / run 2 | 0.9423 / 0.9615 (49/52, 50/52) | 2/5, 3/5 |

`v2` became the default on a mean of 0.9519 against 0.9231. Session 4 spent about US$0.04 on live calls (five eval runs and two rounds of cassette recordings), bringing the catch-up ledger to about US$0.089 of the US$5 budget.

## 1. Why a typed form beats a free textarea when the task space is bounded

A free textarea makes the user write the prompt. "Short estimate, as a table, it's a mobile app" is three parameters hidden in a sentence, and the model has to recover them before it can do the actual work. When the set of useful variations is small and known in advance, you can name those parameters, give each a closed set of values, and let the user pick. That's the typed form. The model gets explicit instructions instead of guessing, and everything around it gets easier to build.

Here the parameters are the brief's three enums in `app/schemas/estimation.py`: `ProjectType` (4 values), `DetailLevel` (3) and `OutputFormat` (3). They are required fields of `EstimateRequest` next to `transcription`. Here is what that buys, layer by layer:

- Bad input costs nothing. An unknown value fails validation before any model call (`tests/unit/test_schemas.py::test_unknown_enum_value_rejected`); on the context endpoint it is a 422 naming the parameter (`tests/api/test_context.py::test_context_rejects_unknown_params`). A textarea would hand the same mistake to a paid model call.
- The compiler checks the contract. `web/src/lib/estimate/choices.ts` declares the values as arrays that `satisfies` the types generated from `contracts/openapi.json`, and the form's label records in `web/src/components/form/estimate-form-schema.ts` are keyed by the generated enums. If the AI service adds or drops a value, `pnpm typecheck` fails. With a textarea there is nothing to drift, but there's also nothing to check.
- Each enum value maps to a template branch, so a template test can assert what each branch says (section 4).
- Every golden eval case carries `project_type`, `detail_level`, `output_format` and `expects_frontend` in front matter (`evals/run_eval.py`, `REQUIRED_KEYS`), so the eval runs the same request every time.
- The rendered prompt goes into the Redis key, so each of the 36 enum combinations gets its own entry (`tests/unit/test_cache_key.py::test_every_enum_combination_has_its_own_key`). Free text gives you a key per phrasing, and two users asking for the same thing in different words never share a hit.
- The choice is visible. `output_format` also picks the markdown layout built in code (`app/services/rendering.py`: a phase rollup table, a task table, or prose per phase). The orchestrator's ruling during planning was blunt: a control with no visible effect is a defect. That's why the result pane has a Structured / Document toggle; Document shows the server's markdown in the chosen layout.

The form did not take the brief's schema literally. The brief's `description` is capped at 2,000 characters, and a meeting transcript doesn't fit in that (the course's own solution raised it to 80k). Decision D8 kept `transcription` (up to `MAX_TRANSCRIPTION_CHARS`, 50,000 by default) and the structured response from M1, because session 5 starts from both.

**Trade-offs.** Every new option is a contract change: schema, OpenAPI snapshot, generated TypeScript, labels, template branch, tests. Combinations multiply: 4 × 3 × 3 = 36 per prompt version, and `tests/prompts/test_estimation_v2.py` renders all 36. The user can't ask for something you didn't anticipate ("phases table, but put costs per phase"). And defaults carry a lot of weight: anyone who leaves the segmented controls alone gets `web_saas` / `medium` / `phases_table`, which is also the combination the replay cassettes and the e2e run are recorded for.

The review panel found a cost of trusting the contract too much. The BFF forwarded `prompt_version` and the enum query values to the AI service unchecked (Task 7 review, finding I2). The AI service would have rejected bad values with a 422 anyway, but the ruling was defence in depth: `web/src/app/api/context/route.ts` now forwards a value only if it is one of the allowed enums or matches `/^v[1-9]\d*$/`, and drops everything else. The price is the values listed twice, pinned to the contract by `satisfies`.

**Alternatives and when to switch.** If users won't pick from controls (people dictating on a phone, say), let an LLM fill the form: structured output with the same enum schema extracts the parameters from free text, and the user confirms or corrects them before the paid call. Keep the textarea-only design for open tasks, where you can't list the useful variations. Section 9 covers the hybrid.

## 2. Why a `.j2` file with a loader is more maintainable than an f-string in the endpoint

An f-string in the endpoint mixes three things that change for different reasons: the request handling, the prompt text, and the logic that assembles the prompt. A template file holds the text and its assembly rules; a loader turns a typed request into the exact `(system, user)` pair; the endpoint just calls the loader. When the prompt changes, the diff is a prompt diff, reviewable on its own, and nothing else in the endpoint moves.

The other half of the argument is reuse. Here, one loader feeds the blocking endpoint, the streaming endpoint, the context endpoint behind the inspector (`render_system`), the eval runner and the cassette recorder (`scripts/record_cassettes.py`). With an f-string inside `POST /estimate`, each of those would need its own copy of the prompt, and the inspector would show a prompt the model never saw the day the copies drifted apart.

`app/prompts/loader.py` exposes the brief's signature, `render_estimation_prompt(request, version="v1") -> tuple[str, str]`, over one module-level `Environment`:

```python
_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    auto_reload=False,
    autoescape=False,  # noqa: S701  # plain-text prompts, not HTML: escaping corrupts transcripts
)
```

Each setting is there for a reason:

- `StrictUndefined` turns a misspelled variable into an exception. The default `Undefined` renders it as an empty string, so a typo silently ships a prompt with a hole in it. `test_missing_template_variable_fails_loudly` checks this.
- `trim_blocks` and `lstrip_blocks` stop `{% if %}` lines from leaving blank lines and indentation in the output. That matters more than it seems: the port was checked byte for byte, and the new system prompt starts with exactly M1's `v4` text (the one pinned as `f041e8c1…`) before the two new enum blocks. Stray whitespace would have broken that check.
- `autoescape=False` because this is plain text going to a model, not HTML. With escaping on, a transcript line like `A < B` would reach the model as `A &lt; B`. Ruff flags the setting (S701), so the line carries its justification.

The templates use the three Jinja features the brief names. `system.j2` includes `examples.j2` with `{% include %}`; `examples.j2` loops with `{% for %}` over the three reference estimations, which still live as typed, tested Python in `app/context/examples.py` (the template only formats them); `system.j2` ends with an `{% if %}` block per enum.

One thing Jinja does not do for you: neutralise the transcript. It never re-evaluates a rendered value, so `{{ 7*7 }}` in a transcript arrives at the model as literal text (`test_template_syntax_in_transcript_is_data`). But a transcript containing `</transcript>` could still close our delimiter. `neutralize()` rewrites our own tags to `[/transcript]` before rendering, kept from M1 as a prompt-injection defence (`test_delimiters_in_transcript_are_neutralised`).

The loader also fails early. `check_prompts()` in `app/main.py` runs in the lifespan, before the provider is built: an unknown `PROMPT_VERSION` stops startup with a message that names it, and every available version is rendered once, so a broken template fails the boot rather than the first request (`tests/api/test_app.py`).

**Trade-offs.** You add a dependency (`jinja2>=3.1.6`) and a second language. Template errors are runtime errors: neither ruff nor mypy can see that `system.j2` uses `output_format`, while both catch a misspelled name in an f-string. The startup check only renders the default enum combination per version, so an error inside, say, the `narrative` branch would surface on the first request that uses it. The template tests render every branch to close that gap. And templates in files are one more place to look when reading the code.

There's a smaller point in favour of templates that's easy to miss: `str.format`-style templates stored in files break on literal braces, and our system prompt contains three JSON documents. PromptLayer's own FAQ tells users to switch from its default f-string parsing to Jinja2 for exactly that reason.

**Alternatives and when to switch.** For a three-line prompt with one variable, an f-string in a small function is fine and type-checked; don't build a loader for it. When the assembly logic gets heavier than the text (many conditional sections, per-tenant fragments, tool definitions), a typed Python builder that returns message lists can beat a template: it's testable, refactorable and checked by mypy. When people outside engineering edit prompts, or prompts must change without a deploy, move to a registry (section 7).

## 3. How a prompt is versioned, and why `v1/`, `v2/` is not optional

A prompt version is an immutable name for one exact prompt. Here that's a directory, `app/prompts/estimation/<version>/`, holding all three templates. The loader lists versions from disk (`available_versions()`, names matching `v[1-9]\d*`), the `PROMPT_VERSION` setting picks the default (now `v2`), `?prompt_version=` overrides it per request on all three endpoints (unknown versions get a 422, `tests/api/test_prompt_version.py`), and the version travels with everything the call produces.

It isn't optional because a lot of other things in the system refer to a prompt and assume it won't change under them:

- Eval reports. `evals/reports/estimation-v1-run1.json` says `v1` scored 0.9231. That sentence is only true while `v1` is the prompt that was scored. Edit `v1/system.j2` in place and every number in the README eval table describes a prompt that no longer exists.
- The response cache. The Redis key includes `prompt_version`, a SHA-256 of the rendered `(system, user)` pair, and `CACHE_SCHEMA` (`app/services/cache.py`). Without that, an answer from the old prompt would be served as if the new one wrote it. The review of Tasks 3 and 4 asked for the 36-combination isolation test to be parametrized over `available_versions()`, so every new version gets it for free; it now runs for `v1` and `v2`.
- Provider prompt caches. OpenAI requests carry `prompt_cache_key=estimator-<version>` (`tests/unit/test_llm_service.py::test_a_v2_request_routes_with_estimator_v2`), which keeps each version's calls routed to the same cache.
- Replay cassettes. The `replay` provider keys recordings by the SHA-256 of the rendered prompt pair. `tests/unit/test_smoke_live.py::test_every_sample_has_a_current_cassette` fails when a prompt change orphans them. It fired in Task 2 and again in Task 6, three failures each time, exactly as planned, and each task re-recorded the cassettes (about US$0.004 each time).
- Logs. Every render emits `prompt_rendered` with the version and the hash, never the content (`test_render_logs_version_and_hash_but_never_content`). When an estimate looks wrong in production, the log tells you which prompt wrote it.
- Rollback and comparison. Going back is a setting change, not a revert. And `v1` and `v2` can run side by side on the same inputs, which is the only way to measure the difference.

Three tests keep the versioning honest. `tests/unit/test_prompts.py::test_pinned_hash` pins the hash of `v1` rendered with the default params, and its comment says the rule: a changed template needs a new version directory. `tests/prompts/test_estimation_v2.py::test_v2_is_v1_plus_the_rule_only` renders all 36 combinations of both versions and checks that removing the one new rule line from `v2` gives `v1` exactly. That test is what lets you read the eval delta as the effect of that one line. The third, `test_v2_includes_only_its_own_templates`, guards against a quiet leak: if `v2/system.j2` included `estimation/v1/examples.j2`, editing `v1`'s examples would change `v2` too.

Decision D9 restarted the numbering under the use-case namespace: `estimation/v1` is a faithful port of M1's `v4`, and M1's `app/prompts/v1..v4` were deleted (their history stays in git and in `evals/reports/`). Naming the port `v5` was rejected because the brief's paths and tests say `v1`. The port was gated before it replaced anything: 1.0 (47/47) against the M1 `v4` baseline of 0.9787 (46/47), tolerance 0.02.

Versioning applies to more than prompts. Task 5 changed the markdown layout built in code, and the orchestrator accepted a `CACHE_SCHEMA` bump from 1 to 2 for it. No prompt changed, but what a cache entry stores did, and a long-running Redis would otherwise have served old markdown under the new code. The general rule: anything that shapes a cached or recorded value needs a version in its key.

**Trade-offs.** Duplication: `v2` copies all three files to add one line, and `user.j2` and `examples.j2` are byte-identical to `v1`'s. A fix to shared text can't be applied to old versions in place; it means a new version and a new eval. A directory name says nothing about who changed what and why; the commit message and the README eval table carry that.

**Alternatives and when to switch.** Git history alone (versions as commits) gives you an audit trail but no runtime selection, no A/B and no side-by-side eval. A content hash as the version is precise (the hash is already logged) but unreadable in a dashboard. A registry with labels (section 7) adds rollout without a deploy. Once no traffic, eval or cassette refers to an old directory, delete it; git keeps it.

## 4. What a template test covers, and what it doesn't

A template test renders the prompt for a given request and asserts things about the string. No model, no network, no keys: `tests/prompts/test_estimation_v1.py` runs its 11 tests in about 0.01 s, and all 49 template tests take about 0.05 s. Its job is to prove that the code assembles the prompt you think it does.

What the branch's template tests cover:

- The transcript lands inside its delimiter block (`<transcript>`, our name for the brief's `<project_description>`).
- `output_format=phases_table` puts the keyword `phases_table` in the system prompt, and `narrative` doesn't.
- `detail_level=detailed` adds the "assumptions per phase" instruction, and `summary` doesn't.
- `project_type` reaches the user message.
- Template syntax inside a transcript stays data, and our delimiters inside it are neutralised.
- An unknown version and a missing variable both fail loudly.
- Two different enum combinations share at least 90% of the system prompt as a prefix (section 5).
- The reference estimations come from the typed source, rendered from `model_dump_json()`.
- The render log carries the version and hash and never the transcript.
- For `v2`: the new rule is present, appears exactly once, and is the only difference from `v1` across all 36 combinations.

What they can't cover:

- Whether the model follows the instruction. The test proves "List assumptions per phase" is in the prompt. It says nothing about whether gpt-4o-mini lists them.
- Meaning. The `phases_table` test checks a keyword. An instruction that said "never use phases_table" would pass it. Keyword tests check wiring, not intent.
- Quality and cost: whether the hours are sensible, whether the tone fits, how many tokens the prompt burns.
- Provider behaviour: caching, truncation, refusals, the effect of instruction order.
- What the user sees. The markdown layouts are built in code and tested separately in `tests/unit/test_rendering.py`.

The clearest evidence is in this branch. The `v1` port passed every template test and scored 47/47 in its first eval. Then the `covers_frontend` check arrived, and over two runs of five cases the same templates produced no frontend task 7 times out of 10. Nothing in the template tests could have told you. The prompt already said, in step 5 of the task decomposition, "Give every client-facing surface the client asks for … its own frontend task or tasks". The wiring was fine. The model mostly ignored it.

**Trade-offs.** Template tests are cheap and deterministic, so they run in `make check` on every commit. The risk is false confidence: a green prompt suite feels like a tested prompt. Snapshot-style tests (the pinned hash) are good at catching any change and bad at saying whether the change was right; they push you to version instead (section 3).

**Alternatives and when to switch.** For behaviour you need evals (section 6). In between sit cheap deterministic checks on real or recorded outputs: schema validation, grounding of quotes, totals computed in code. This project does all three in the service, which is why the eval checks are mostly about content.

## 5. Prompt-cache-aware template ordering

Providers can cache the processed prefix of a prompt and charge less, and answer faster, when the next request starts the same way. OpenAI does this automatically for prompts of at least 1,024 tokens, matching in 128-token steps; Anthropic caches up to an explicit `cache_control` breakpoint. Either way, only an identical prefix counts. So the order inside a template is a cost decision: put what never changes first, and what varies per request last.

`system.j2` is ordered that way: role, method, rules and the three reference estimations (the long, static part, about 22k characters), then `<output_format>` and `<detail_level>` at the very end. `project_type` doesn't appear in the system prompt at all; it goes in the user message ("Project type: mobile_app."). The 36 combinations therefore produce only 9 distinct system prompts per version, and any two of them share about 98% of the shorter one as a prefix (98.18% at worst for `v1`). `test_enum_blocks_come_after_the_static_prefix` asserts at least 90% for two combinations that differ in both enums, so a future edit that moves an enum block to the top fails `make check`.

The live numbers back it up. The `v2` cassettes in `tests/cassettes/` record 6,144 of 6,742 input tokens read from OpenAI's cache, 6,400 of 6,567 and 6,272 of 6,488 (Task 6), and the `v1` recordings in Task 2 looked the same. All of them are multiples of 128. For comparison, the M1 baseline run, made before requests carried `prompt_cache_key`, read 0 cached tokens.

**Trade-offs.** The enum instructions sit far from the rules they qualify, at the end of a long prompt. Late instructions tend to carry weight, which is probably fine here, but it's a placement chosen for cost, not for the model's reading order. And the shared prefix only pays where the provider caches partial prefixes. Anthropic's adapter puts one breakpoint on the whole system text (`app/services/providers/anthropic_provider.py`), so a different enum tail means a different cache entry there: 9 entries instead of one.

**Alternatives and when to switch.** Move the enum instructions out of the system prompt into the user message, and the system prompt becomes byte-identical across all 36 combinations: one cache entry per version, on both providers. The brief asks for the conditional blocks in `system.j2` and tests the system text, so this branch kept them there. Switch when the combinations grow, or when Anthropic traffic matters. Or, staying with the current layout, split the Anthropic system prompt into two blocks with a breakpoint after the static part. Either way, measure with `usage.cached_input_tokens` before and after; that's what the column is for.

## 6. Template tests vs evals, and what two runs taught

Template tests answer "did we build the prompt we meant to build?" Evals answer "does the model do what we want with it?" You need both because they fail on different things. A template test that breaks means a bug in our code, and it breaks the same way every time. An eval that drops means the model's behaviour changed, or it means nothing at all, because sampling is noisy.

The eval here is `evals/run_eval.py` over five golden cases. Each case gets about ten checks: schema validity, three-point order, hours within 4 to 80, QA/devops/project-management coverage, grounded quotes, valid task basis, narrative language, and now `covers_frontend` for cases whose front matter sets `expects_frontend: true`. One run costs about US$0.0065 on gpt-4o-mini. It runs by hand with `make eval`, never in `make check` or CI.

The noise lesson came in two steps. Task 2's `v1` port scored 1.0 (47/47) in a single run, and the brief said to record that as the baseline. With the gate's 0.02 tolerance, any later report then needed at least 0.98, so a single failed check out of 47 (0.9787) would fail the gate. One unlucky sample would have blocked a good prompt. The orchestrator ruled that Task 6 compares the versions on the mean of two runs each, interleaved v1, v2, v1, v2, for about US$0.03 more.

The two runs showed how much a single run can mislead:

- `v1` scored 0.9231 twice, but its frontend coverage went 2/5, then 1/5.
- `v2` went 0.9423, then 0.9615, with coverage 2/5, then 3/5.
- The course-meeting case passed `covers_frontend` with `v1` in run 1 and failed it with `v2` in run 1.
- Means: 0.9519 for `v2` against 0.9231, coverage 5/10 against 3/10.

`v2` met the promotion rule (mean score at least `v1`'s minus 0.02, coverage rate at least `v1`'s), so it's the default. Look at the size of the effect, though: the gap is two cases out of ten, and each version moved by one case between identical runs. The improvement is directional and within about one case of run-to-run noise. Five cases and two runs can't separate a real effect of that size from luck.

The check itself has blind spots worth knowing before you trust it. It passes when the estimate has at least one `frontend` task, not one per surface, so the course meeting (a member app and a staff panel) passes with a single frontend task. All five golden cases set `expects_frontend: true`, so nothing catches a prompt that starts adding frontend work to a pure data pipeline. And the vague marketplace case got no frontend task in any of the four runs; the reports store task counts but not phases, so we can't tell whether the work went to `ux_ui` or `backend` instead.

The new baseline is `v2` run 2 (0.9615), the stricter of the two `v2` runs. Run 1 passes it (0.9423 ≥ 0.9415). A later run needs 49/52; at 48/52 (0.9231, both of `v1`'s runs) it fails. That's tight, and a plain unlucky `v2` run could fail it too.

**Trade-offs.** More runs and more cases cost money and time; fewer make the numbers decorative. A strict gate catches regressions and also blocks on noise. A loose one lets real regressions through.

**Alternatives and when to switch.** For a decision that matters, run each version several times, compare per case (a paired comparison, since each case is its own difficulty level), and report a spread, not one number. Grow the golden set with cases that should *not* get a check (an `expects_frontend: false` case is the obvious next one) and checks that count per surface. Those are the `v3` candidates. For a gap like frontend coverage, a deterministic post-check in code can beat any prompt wording: detect the surfaces the transcript names, and flag or retry an estimate that has no frontend task for them, the same way totals and grounding already live in code.

## 7. Prompt registries (Langfuse, PromptLayer) and when to adopt one

A prompt registry stores prompts outside the code, as versioned objects you fetch at runtime by name. Both tools work the same way at the core. In Langfuse, every edit creates an immutable numbered version, and labels are movable pointers to versions: `production` is what `get_prompt(name)` returns by default, `latest` follows the newest, and you can add your own (`staging`, a tenant, `prod-a` / `prod-b` for an A/B test). `prompt.compile(**variables)` fills `{{variable}}` placeholders, and passing the prompt object to a traced generation links each output to the prompt version that produced it. PromptLayer's Prompt Registry has the same shape: `run(prompt_name=..., prompt_release_label="prod", input_variables=...)`, with templates parsed as f-strings by default or as Jinja2.

The appeal is what you can do without a deploy: change the prompt, promote a version by moving a label, roll back by moving it again, split traffic between labels, and see quality and cost per prompt version next to the traces.

This branch has a small registry already, made of files: version directories in git, `PROMPT_VERSION` as the "production label", `?prompt_version=` for per-request selection, `available_versions` in `GET /api/v1/context`, the version and hash in every log record and response, and the eval reports as the scorecard. What it doesn't have is a way to change a prompt without a pull request and a deploy. For a one-team, one-service project, that's a feature: every prompt change goes through review and `make check` (template tests, the pinned hash, the cassette guard), and by convention through an eval before it becomes the default.

**Trade-offs.** A registry moves the prompt out of the review path. The template tests and the pinned hash protect files in the repo; a label moved in a web UI skips them, unless CI fetches and tests the registry's version too. It adds a runtime dependency: a network fetch on the request path, which needs a client-side cache and a fallback prompt for when the registry is down. Code and prompt can drift apart: a prompt that expects a variable the code doesn't send. And a hosted registry stores your prompts and often your traces, which may contain client transcripts; Langfuse can be self-hosted if that matters. The template language may change too. Langfuse's `compile()` fills `{{variable}}` placeholders, so our `{% if %}` and `{% include %}` blocks would become separate prompts, composed prompts or code there; PromptLayer's Jinja2 mode would keep more of them.

**When to switch.** Adopt one when the people who tune prompts are not the people who deploy code, when you need to change or A/B prompts per tenant without a release, or when many prompts across several services make "which version produced this output?" hard to answer from logs. A good middle path: keep the templates in git as the source of truth and have CI push each merged version to the registry, using labels only for rollout.

## 8. Jinja's `SandboxedEnvironment`, and when templates come from untrusted authors

A normal Jinja `Environment` lets a template reach Python attributes, and from an object you can walk to `__class__`, `__mro__`, `__subclasses__()` and on to code execution. That's server-side template injection. It only matters when someone you don't trust writes the template source. `jinja2.sandbox.SandboxedEnvironment` compiles templates so unsafe attribute and method access raises `SecurityError`, and `ImmutableSandboxedEnvironment` also blocks changes to lists, dicts and sets passed in.

We don't use it, and that's right for this code. Our templates are written by us, live in git and go through review. Request data only ever enters as *values*, and Jinja doesn't evaluate values: `test_template_syntax_in_transcript_is_data` sends `{{ 7*7 }}` and `{% include 'x' %}` in a transcript and checks they arrive as literal text, with no `49`. The dangerous line would be `_env.from_string(something_a_user_sent)`, and it doesn't exist. The version string can't pick an arbitrary file either: `_check()` accepts only names in `available_versions()` before `get_template` runs, and the API answers `../v1` or `v1/../../x` with a 422 before any model call (`tests/api/test_prompt_version.py::test_bad_prompt_version_is_422_json`).

You need the sandbox when template source comes from outside your team: users who customise their own prompt in the app, tenants editing prompts in an admin panel, a registry that non-engineers can edit, or templates an LLM generates.

**Trade-offs.** The Jinja docs say plainly that the sandbox is not a complete security solution. It doesn't limit CPU or memory, so a tiny template can still produce enormous output, and you need your own limits and error handling around rendering. Whatever you pass into the context is reachable, so pass only the data the template needs, never objects with side-effecting methods. And it does nothing about prompt injection: a user-written template can still tell the model to ignore its rules. That's a separate defence (the delimiter neutralisation, the "transcript is data" rule and the grounding checks here).

**Alternatives.** The best option is usually to not accept templates at all. Give users typed knobs (this branch's form is exactly that) or a fixed slot, like a "tone" text pasted inside a delimited block of a template you own. If users really must write templates, a logic-less language with substitution only shrinks the attack surface, and rendering in a separate process with a timeout handles the resource problem.

## 9. Typed forms vs chat vs a hybrid "form + refine" UI

Three shapes for the same product. A chat suits open-ended tasks where the user discovers what they want by talking. A form suits a bounded task with known parameters. The hybrid starts with a form that produces a structured result, then lets the user refine that result in natural language ("drop the mobile app", "make QA 20% bigger"), with every refinement applied to the structured object rather than starting over.

Session 3 built a chat, and it was the wrong shape for an estimator in a telling way: each turn was estimated on its own, so the thread looked like a conversation but had no memory. Session 4 replaced it with one run per form submission. A comment in `web/src/components/workspace/workspace.tsx` says so ("a form, not a thread"). Regenerate reuses the run's own transcript, choices and prompt version, skipping the exact-match cache, whatever the form says now.

The form also made room for things a chat bubble can't hold. Results open in a resizable split view, with the transcript on the left and the estimate on the right. Hovering or focusing a requirement highlights its quote in the transcript and scrolls to it, by keyboard too. `web/src/lib/evidence.ts` re-implements the AI service's grounding normalisation (NFKC, typographic quotes and dashes, Python's `casefold` and `\s`, collapsed whitespace, trimmed edge punctuation) so that every quote the server calls grounded gets a mark in the browser. That's verification UI: the user can check the estimate against what the client said.

A richer layout brings its own bugs. The review panel found that below 768 px, where the panes become tabs, switching to the Transcript tab unmounted the estimate pane mid-run (Task 7, finding I1): Esc no longer stopped the stream and the live-region announcements were lost. The fix keeps both panes mounted (`forceMount` in `split-view.tsx`), hides the inactive one with CSS, and announces how a run ends from outside the tabs. A chat thread never has this problem, because nothing in it is hidden.

**Trade-offs.** Chat is flexible, but it puts prompt engineering on the user, makes runs hard to compare and evaluate, and hides parameters in prose. A form is predictable and testable, but rigid. The hybrid gives the best experience and costs the most: you need a structured document as the source of truth, edits applied to it, a version history of the estimate, and a clear rule for when a refinement means re-estimating from the transcript instead of patching the result.

**When to switch.** Stay with the form while the product's job is "estimate this transcript with these settings". Move to the hybrid when users come back to adjust the same estimate, which is what session 5 sets up with conversational memory and attachments. Use pure chat only where the task really is open.

## Quiz

**1.** In `estimation/v1`, `project_type` goes into the user message, while `detail_level` and `output_format` are blocks at the end of the system prompt. What does that ordering buy, which test protects it, and why does it help OpenAI more than Anthropic in this codebase?

<details>
<summary>Answer</summary>

The long static part of the system prompt (role, rules, about 22k characters of reference estimations) stays an identical prefix across requests, so the provider's prompt cache can reuse it. Keeping `project_type` out of the system prompt cuts 36 combinations to 9 distinct system prompts, which share about 98% as a prefix. `test_enum_blocks_come_after_the_static_prefix` asserts at least 90% shared prefix for two combinations that differ in both enums. OpenAI caches prefixes automatically in 128-token steps (6,144 of 6,742 input tokens came from the cache when the `v2` course-meeting cassette was recorded). The Anthropic adapter puts one `cache_control` breakpoint on the whole system text, so a different enum tail is a different cache entry there. A second breakpoint after the static part, or moving the enum blocks into the user message, would fix that.
</details>

**2.** A teammate fixes a typo in `app/prompts/estimation/v2/system.j2` in place and opens a pull request. What fails, and what keeps "working" but now lies?

<details>
<summary>Answer</summary>

Fails: `test_v2_is_v1_plus_the_rule_only` (removing the rule from `v2` no longer gives `v1`), and `test_every_sample_has_a_current_cassette`, because the cassette key is the hash of the rendered prompt and the e2e stack replays the default version, `v2`. Edit `v1` instead and `test_pinned_hash` fails too. What lies: the README eval table and `evals/baseline.json` still say `v2` scored 0.9519 mean / 0.9615, but that was a different prompt, and logs or responses saying `prompt_version: v2` no longer identify one exact prompt. The right move is a `v3` directory, a template test for the change, re-recorded cassettes and a new eval.
</details>

**3.** `test_phases_table_keyword_only_for_phases_table` passes. What does that prove, and what doesn't it?

<details>
<summary>Answer</summary>

It proves the `output_format` branch is wired: the `phases_table` value reaches the template, the right `{% if %}` branch renders, and the `narrative` branch doesn't contain the keyword. It doesn't prove the model groups work by phase, writes one-sentence rationales, or even reads the instruction the way we meant. It doesn't check meaning either: an instruction saying "never use phases_table" would pass. The visible layout is built in code and tested in `tests/unit/test_rendering.py`; model behaviour needs an eval.
</details>

**4.** `v2` averaged 0.9519 against `v1`'s 0.9231, and frontend coverage went from 3/10 to 5/10. A colleague says "v2 fixes the frontend gap". How do you answer?

<details>
<summary>Answer</summary>

It improves it, directionally. The gap between the versions is two cases out of ten, and each version moved by one case between two identical runs (`v1` 2/5 then 1/5, `v2` 2/5 then 3/5), so the difference is within about one case of noise. Half the runs still had no frontend task, and the vague marketplace case got none in any of the four runs. The check is also generous: one frontend task passes it, even when the transcript names two surfaces, and no golden case tests that a non-frontend project doesn't get one. `v2` was promoted because it met the rule (no score regression, coverage at least as good), not because it was shown to be better.
</details>

**5.** Why was a single-run perfect baseline a problem for the eval gate, and what did the branch do instead?

<details>
<summary>Answer</summary>

The `v1` port scored 1.0 (47/47) once, and that became `evals/baseline.json`. With a 0.02 tolerance the next report needed at least 0.98, so one failed check out of 47 (0.9787) would fail the gate. One noisy sample would decide. Task 6 ran each version twice, interleaved, and compared means, with the promotion rule written down before the runs. The new baseline is the higher-scoring `v2` run (0.9615), which keeps the gate strict: a later run needs 49/52.
</details>

**6.** The loader uses a plain `Environment` with `autoescape=False`. Is that a security hole? When would you switch to `SandboxedEnvironment`, and what would it still not protect against?

<details>
<summary>Answer</summary>

No. Autoescaping is about HTML output; here it would only corrupt transcripts. Template injection needs untrusted template *source*, and ours comes from the repo. Request data enters only as values, which Jinja never evaluates (`test_template_syntax_in_transcript_is_data`), and versions are checked against `available_versions()` before `get_template`. Switch to `SandboxedEnvironment` (or `ImmutableSandboxedEnvironment`) when users, tenants, a registry edited by non-engineers, or an LLM write templates. It still doesn't limit CPU or memory, can't hide data you pass into the context, and does nothing against prompt injection aimed at the model.
</details>

**7.** When would you move these prompts from version directories in git to Langfuse or PromptLayer, and what would you lose?

<details>
<summary>Answer</summary>

When the people tuning prompts aren't the people deploying code, when prompts must change or be A/B tested per tenant without a release, or when many prompts across services make it hard to trace an output back to its prompt. Both tools give you immutable versions, movable labels (`production`, `prod`) and links from traces to prompt versions. You lose the review path (template tests, the pinned hash and the cassette guard don't see a label moved in a UI), you gain a network dependency that needs caching and a fallback, and Jinja features like our `{% if %}` blocks may need restructuring. A middle path keeps git as the source of truth and has CI publish to the registry.
</details>

**8.** The AI service already rejects unknown enum values and prompt versions with a 422. Why does the BFF validate them too, and what review finding about the split view shows that a form-based UI has costs a chat doesn't?

<details>
<summary>Answer</summary>

Defence in depth (Task 7, finding I2): the BFF forwards only values from the allowed enum lists or matching `/^v[1-9]\d*$/` and drops everything else, so arbitrary query strings never reach the private AI service. The lists are pinned to the generated contract with `satisfies`, so they can't drift silently. The split-view finding (I1): below 768 px the transcript and estimate become tabs, and switching tabs unmounted the estimate pane mid-run, losing Esc-to-stop and the live announcements. Both panes now stay mounted and CSS hides the inactive one. A chat thread hides nothing, so it never had this kind of state-lifetime bug.
</details>
