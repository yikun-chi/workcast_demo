# WORKCAST: context and instructions for agents

This is the single agent guide for this repository. `AGENTS.md` and `CLAUDE.md`
only point here so different tools load the same instructions. Update this file
when project context, design principles or file-placement rules change; do not
create another agent guide, repository map or session handoff document.

## Project and product context

WORKCAST, by Emergent Science, simulates how people and work respond to organizational
changes. The repository is [yikun-chi/workcast_demo](https://github.com/yikun-chi/workcast_demo).
It is one Python application with a shared browser UI and multiple instances. Keep
one source checkout; there is no separately maintained `dist/org_simulation` platform.

The audience is managers exploring decisions and readers assessing the evidence.
Every instance uses the same framing:

1. **Observed before → change → actual outcome, other prediction, simulation prediction.**
   Before-period observations provide context and may calibrate the model. Do not
   simulate a before period for display. Score the after-change prediction against
   actual outcomes, alongside an understandable non-simulation comparison method.
2. **Alternative actions and their impact.** Explore changes that were not observed
   by comparing simulations under matched assumptions. Keep this section separate
   from the comparison against actual outcomes.

Use “Actual outcome”, “Other prediction” and “Simulation prediction” in the UI.
Avoid “engine prediction”, “forecast”, “trial” and unexplained statistical acronyms
in reader-facing labels. A scenario named `baseline` internally represents the
change that occurred; it is distinct from the non-simulation “Other prediction”.
Keep internal identifiers stable. Explain a comparison method in ordinary language.

Each instance is self-contained in its tabs; the landing page selects an instance.
Show the change, reference condition, actual and predicted impact, and prediction
error together. Do not split the same attrition outcome between competing sections.
Alternatives follow; supporting metrics open on selection. Editing belongs in
Ontology, Data and Scenarios. Results, Scenarios, Data and Ontology stay visible;
inspection pages live under More. Use scenario `short_title` in tables. Label
simulated interviews as simulated: no real employee said those statements.

| Instance | Question | Model family |
|---|---|---|
| `trip` | Trip.com hybrid work, attrition and satisfaction | Workforce twins |
| `bpi19` | Procurement staffing, queues and completion time | Process and capacity |
| `openrouter` | AI app token demand, routing and spending | Market |
| `ctrip` | Ctrip call-centre home working, output and attrition | Workforce twins |
| `fedwork` | Federal workforce separation after policy changes | Workforce cohorts |
| `btos_ai` | Business-sector AI adoption | Adoption |
| `so_chatgpt` | Stack Overflow question volume after ChatGPT | Adoption and displacement |
| `aei_tasks` | Occupation mix of AI-assistant use | Adoption |

Trip.com and procurement each have an original policy alternative and an AI
assistant alternative. Their AI impacts are assumption-based workload estimates;
these datasets contain no observed AI intervention to validate those alternatives.
The authored task workflow in `examples/` is a separate demonstration. Keep its
assumptions and any future AI-as-CEO roleplay separate from real-data validation.
`so_survey` is a feasibility investigation, not a registered instance.

## Evidence and fidelity principles

- **No outcome leakage.** Neither treatment nor control outcomes observed after a
  policy change may calibrate its prediction. This includes the contemporaneous
  Trip.com office-only control. Use information available at the prediction cutoff;
  a record's historical date alone does not establish when it was available.
- **Honest comparisons.** Use the same outcomes, horizons and information boundary
  for the simulation and other prediction. Improve accuracy through justified
  mechanisms and pre-change validation, never by tuning to the scored answer.
  Report weaknesses; do not promise the simulation wins every metric.
- **Computed results.** UI, reports, insights and validation numbers must come from
  evaluation/run artifacts and their builders. Do not type improved numbers into
  generated output. Authored assumptions must be explicitly identified as assumptions.
- **Current results with provenance.** `runs/<id>/evaluation.json` is the current
  scored result. Avoid competing result copies, iteration labels and model-history
  commentary in the product. Retain source manifests, cited prior revision logs,
  frozen protocols and existing sealed snapshots; do not rewrite research provenance
  as part of a cleanup.
- **Demographics.** Protected demographic attributes may appear in descriptive
  tables, but must not drive behavioral functions, priors or prompts.
- **Causal language.** Label a contemporaneous control as a control, not a before
  period. Describe historical period differences as such; an observed difference
  alone does not establish an isolated causal effect.

Specific evidence boundaries to preserve:

- Trip.com currently excludes both groups' post-change outcomes from calibration,
  but inherited priors include outcome-based selection in their revision history.
  Describe its results as retrospective, not a pristine prospective holdout.
- Procurement selects its specification using January–June fitting and July–August
  validation, then refits on data before September 1. Predictions receive actual
  incoming orders and state at each cutoff; future case activity is withheld.
  This is a conditional operational prediction, not a prediction of all future demand.
- OpenRouter fits parameters from backtests ending before each cutoff, but archived
  evaluations supply later prices/model launches and categories derived from
  all-period usage. These are conditional market scenarios; truncating usage alone
  does not fix category leakage.
- Instance follow-ups are tracked in issues [#4–#9](https://github.com/yikun-chi/workcast_demo/issues?q=is%3Aissue+assignee%3Asumervaid),
  assigned to Sumer (`sumervaid`): OpenRouter categories and future inputs, board
  D4/E3 method alignment, federal data availability and invalid cohort rates, and
  access to original snapshots. Check current issue status before making claims.
  The application architecture does not resolve these scientific/data questions.

## Architecture and design principles

- **Kernel authority.** The simulation owns time, state, capacity and constraints.
  Policies and task planners propose decisions. They cannot invent capacity, change
  effort assumptions or bypass domain validation. Framework concurrency is software
  execution, not simulated staffing; network latency is not business duration.
- **Ports and adapters.** `orgsim/application/` defines framework-independent ports
  and use cases. `orgsim/adapters/` implements storage, snapshots, legacy-instance
  integration and planner integrations. `orgsim/composition.py` binds instance services.
  Keep SDK types, HTTP clients and concrete persistence out of the core ports.
- **Interchangeable planners.** LangGraph is optional, not the required foundation.
  The task workflow accepts `rule`, `langgraph` or an installed `module:factory`
  implementing `TaskPlanner[Observation, Plan]`. Microsoft Agent Framework can be
  integrated through that same contract; no Microsoft adapter is bundled. Credentials,
  SDK execution and framework checkpoints belong inside adapters.
- **Separate contracts.** Existing instances use seat policies in `orgsim/policies/`.
  The authored workflow uses task assignments over a fixed dependency graph in
  `orgsim/workflow/`. Adding a task planner does not automatically replace those seat
  policies. Dynamic task creation needs its own domain contract and kernel validation.
- **Portable decisions and replay.** The workflow filters effective and availability
  timestamps, validates plans and persists decisions before simulation. Keep the
  decision journal independent of framework checkpoints. Preserve stable command IDs,
  seed, planner/model/prompt identity and usage metadata; unknown usage is null.
  Replay must work without a planner or credentials. External calls must tolerate
  retries; local journals do not guarantee exactly-once external API execution.
- **Incremental boundaries.** Existing world evaluators still perform internal file
  IO and batch runs behind compatibility adapters. Do not claim complete isolation
  of legacy models or silently change their numerical behavior during a refactor.
- **One shared UI.** The FastAPI server assembles services and serves the build-free
  ES-module UI. World-specific computation belongs in world modules, not routes or
  browser code. Instance-specific data, parameters and scenarios live with the instance.

Technical details belong in [architecture](docs/architecture.md),
[task planners](docs/task-planners.md) and [contracts](docs/contracts.md).
Keep agent instructions here; those documents explain the implementation.

## File placement and documentation ownership

Use this table before creating a file. Extend the existing owner rather than adding
a second guide. Update links when moving content.

| Content or change | Where it belongs |
|---|---|
| Project context, agent rules, design principles, placement and verification policy | `agent.md` only; `AGENTS.md` and `CLAUDE.md` remain pointers |
| Operational quickstart: Python/uv, keys, download, run, deployment status and checks | `README.md`; keep architecture and extension explanations out |
| Detailed installation, acquisition, reproduction, deployment and troubleshooting | `docs/setup.md` |
| Documentation navigation | `docs/README.md`; link to owners rather than repeat their instructions |
| Product overview, instance catalog and evidence scope | `docs/overview.md` |
| Application/model architecture and boundaries | `docs/architecture.md` |
| Task-planner architecture, framework integration, replay and runnable commands | `docs/task-planners.md` |
| Canonical file, HTTP and planner interface shapes | `docs/contracts.md`; update with contract changes |
| UI behavior and layout | `docs/ui.md` |
| Research foundations and prior sources | `docs/literature/foundations.md` |
| Computed validation and reports | `docs/validation*.md`, `instances/<id>/reports/report.json`; edit their builders, then regenerate |
| Frozen research protocols and data feasibility | Existing `docs/plans/` files; preserve cited paths, not a place for current setup instructions |
| Authored runnable examples | `examples/`; short README links to the technical guide in `docs/` |
| Instance discovery and command entry points | `orgsim/instances.py`, `orgsim/cli.py`; domain computation stays in models/services |
| Application ports/use cases | `orgsim/application/`; framework-independent orchestration |
| Framework/storage/snapshot adapters and composition | `orgsim/adapters/`, `orgsim/composition.py`; external planners may live in installed packages |
| Authored task contracts, scheduler and CLI | `orgsim/workflow/` |
| Shared clock, scheduling and capacity primitives | `orgsim/kernel/` |
| Scientific model, world-specific metrics and Results presentation | `orgsim/worlds/`; workforce, process, market, adoption and supporting survival code |
| Seat-policy integrations | `orgsim/policies/`; per-instance choices in `instances/<id>/policies/seats.yaml` |
| Shared ontology, scenarios, evaluation, interviews and run storage | Corresponding `orgsim/ontology/`, `scenarios/`, `evaluation/`, `insights/`, `store/` |
| HTTP routes and shared browser pages | `orgsim/server/app.py`, `ui/`; routing in `ui/app.js`, tokens in `ui/theme.css` |
| Instance metadata, sources, ingest, bindings, calibration, scenarios and report builder | `instances/<id>/`; checklist in `instances/_template/README.md` |
| Repository acquisition and report-generation tools | `scripts/`; avoid workstation-specific paths in normal workflows |
| Verification | `tests/`; dataset-dependent checks carry the `data` marker |
| Shared references and their provenance | Ignored `data/`; tracked `data/manifests/`, including compact release snapshot records |
| Public saved responses and static/release tooling | `public-data/`, `scripts/export_site.py`, `scripts/release_snapshot.py`; generated bundles/archives in ignored `build/` |
| Downloaded/normalized instance inputs and run outputs | Ignored `instances/<id>/data/` and `runs/<id>/` |
| Separate ensemble/publishing research | `board/`; its README owns that workflow |
| Financial illustrations from sealed snapshots | `value_cases/`; its README owns rebuild/refresh commands |

Examples: a Microsoft planner integration changes an adapter and
`docs/task-planners.md`, not the root quickstart or simulation kernel. A new instance
reuses an existing world where possible; add a new world module only for a new model
family. Code does not become instance-specific just because only one instance
currently uses its world. A new required API key belongs in the README key table and
the relevant detailed setup instructions. Generated report wording belongs in its
builder, not a manual edit to the generated Markdown.

## Working and verification

Start with `git status --short` and inspect existing changes. Read the owning guide
above and relevant implementation before editing. Work in the existing checkout;
do not overwrite user changes. Read [README.md](README.md) for commands and
[docs/setup.md](docs/setup.md) for full reproduction rather than duplicating setup here.

- Use Python 3.12, `uv.lock` and the editable checkout. `.venv/bin/python` uses the
  current environment; preserve optional extras when using `uv sync`/`uv run`.
  There is no Node build step. Default simulations, template interviews and both
  bundled task planners require no model API calls.
- Keep secrets outside tracked files. OpenRouter data retrieval reads
  `OPENROUTER_API_KEY` or `~/.secrets/openrouter.key`; do not print credentials.
  Check ignore rules and staged changes before sharing. Downloaded data, run traces,
  local PDFs, virtual environments and caches stay local. No code license is selected.
- Add instances with the [template checklist](instances/_template/README.md).
  Register new model families in `orgsim/worlds/__init__.py` and add corresponding
  ontology/people and interview handling. Preserve the common Results contract.
- Reports are generated by `instances/<id>/reports/build_report.py`; validation
  builders live in `scripts/build*_validation*.py`. Confirm which builder owns the
  target document. Refresh from current artifacts; do not rerun expensive evaluations
  merely to reorganize documentation or regenerate unchanged numbers.
- Model, input and calibration changes can invalidate saved AI comparisons through
  fingerprints. Re-evaluate affected behavior as needed; do not remove staleness
  checks to make an old result appear current.
- **Run-folder cleanup:** preserve runs referenced by current evaluations,
  explorations, insights, validation records, reports and latest pointers, plus the
  latest completed run per scenario. Resolve IDs across scenario folders: federal
  evaluations also reference `development` runs. Remove only unreferenced obsolete
  or abandoned runs after checking for active jobs; compare retained file hashes
  and served Results/Insights before and after. Preserve workflow replay journals.
  [Issue #11](https://github.com/yikun-chi/workcast_demo/issues/11) records existing
  Stack Overflow run-ID collisions; deleting duplicate references does not repair
  overwritten artifacts.
- **Documentation-only work:** check local links/anchors, example paths and CLI
  flags, search for stale references and run `git diff --check`. Do not add tests
  that merely mirror prose or claim unchanged runtime behavior was retested.
- **Code/model work:** run relevant tests; before claiming application behavior works,
  run `.venv/bin/python -m pytest tests -q` with the required data/evaluations and
  optional extra if affected. On a fresh checkout, `pytest -m 'not data'` is the
  portable subset; report it as such. Do not download or rerun everything when a
  missing-data limitation can be reported clearly.
- **UI/served-result work:** also run the Trip.com and procurement browser smoke
  pages, require `DONE errors=0`, and visually inspect the affected Results pages.
  Commands are in [setup verification](docs/setup.md#verification). Restart the
  local server after Python changes or use `--reload`; identify the process before
  stopping it. Avoid a process-name search that matches its own shell command.
- Keep commits and pushes within the user's authorized scope; existing session
  authorization applies. Report what changed, the checks actually run and limitations.

## Public website and releases

The public demo uses `workcast.yikun.io` on GitHub Pages. The `workcast` CNAME in
GoDaddy points to `yikun-chi.github.io`. `.github/workflows/pages.yml` builds and
publishes changes to the shared UI or committed `public-data/` snapshots on `main`.
It requires no scientific dependencies, data downloads, simulations or model keys.
The local FastAPI application remains interactive and unauthenticated on loopback.

Static mode is an adapter in the same UI, selected by generated HTML metadata.
It preserves the common framing and saved alternatives, rejects writes and hides
run/edit controls. Keep raw table rows, individual input records and full traces
out of the public website export. Development fixtures are never published evidence.
Update snapshots through `scripts/export_site.py`; do not hand-edit their values.

GitHub Releases separately preserve full datasets and cleaned runs, including
traces and workflow replay journals. Snapshot manifests pin every file and retain
source licensing and known evidence limitations. Restoring a snapshot must never
overwrite different local data or escape the checkout. Keep the compact release
record in `data/manifests/snapshots/`; large archives belong in release attachments.
Use the workflow in `docs/setup.md`, and preserve existing source visibility and
DNS settings unless the user requests a change. Build output is generated, not a
second maintained platform.
