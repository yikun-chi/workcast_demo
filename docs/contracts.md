# Contracts

The public site has a separate [saved-response contract](#11-public-snapshots-and-release-archives)
using the same Results and scenario documents.

The agreements between the platform package `orgsim/`, the instances under `instances/` and the UI under `ui/`.
Change a contract here in the same change that alters it.

Application and planner extension contracts are in section 10. Existing instance
files and HTTP response shapes are unchanged by the application-service boundary.

## 1. Instance folder

`instances/<id>/instance.yaml` must include `id`, `title`, `company`, `problem` (the business question, one
sentence, shown as the card title), `situation` (two sentences: what the company did), `data_used` (one or two
sentences: the dataset and what it records), `intro` (one concise paragraph: what is simulated and what the
alternative asks), `world_type`
(`process`, `workforce`, `market` or `adoption`), `world` (one paragraph), `clock.tick: 1h`, `clock.coverage`,
`scenarios: {baseline: <id>, alternative: <id>, additional_alternatives?: [<id>, ...]}`, `protocol_line` (one sentence on how the result is kept honest)
and `status`.

| Path | Required | Read by |
|---|---|---|
| `manifests/sources.json` | yes | provenance: URL, retrieval date, hash, size, license of every source file |
| `ingest/run.py` with `main(ctx)` | yes | `orgsim ingest <id>`: raw -> `data/normalized/*` + `summary.json` |
| `ontology/bindings.yaml` | yes | `orgsim.ontology.bindings` (schema in the module docstring); Ontology and Data tabs |
| `policies/seats.yaml` | yes | `orgsim.policies.registry`: `default:` and `seats:` with `adapter: rule|llm|local` |
| `calibration/*` | yes | the world module; fitted on the training window only, never on scored outcomes |
| `scenarios/baseline.yaml` + the alternative | yes | `orgsim.scenarios`: `extends:` deep-merges, `seeds:`, `horizon_days`, `short_title`, `world:`, `interventions:` |
| `evaluation/protocol.yaml` | yes | the world module's `evaluate()` |
| `reports/build_report.py` -> `report.json` | yes | Results tab narrative (section 6) |
| `ui/pages.json` + pages | optional | detailed views embedded in Results (section 7) |
| `data/raw`, `data/normalized` | generated | git-ignored |

An optional integer `order` sets the instance's place on the landing page (lower first; default 100, then by id).

Scenario files not named in `instance.yaml` are listed with role `other`: hidden from the UI, runnable from the CLI.
Additional named alternatives have stable role keys `alternative_2`, `alternative_3`, etc.
The original `alternative` key remains the primary policy alternative.

An AI scenario declares `exploration: {note, assumption_basis, sources: [{title, url, note}]}`
and an `ai_assist` intervention with `activities`, `coverage`, `time_saved`,
`review_overhead`, `rework_rate`, and `rework_effort`. Fractions use 0–1; review
overhead may be up to 2 and correction effort up to 3. Resulting effort must be positive.

## 2. World module (`orgsim/worlds/<type>.py`)

```python
class World:                                        # satisfies orgsim.kernel.world.World
    @classmethod
    def from_instance(cls, ctx, scenario: dict, seed: int) -> "World": ...
    def run(self, writer: RunWriter) -> RunSummary: ...   # emits trace events; writes summary/metrics/twins

def evaluate(ctx, scenario_ids: list[str]) -> dict:      # writes runs/<id>/evaluation.json
def results_view(ctx) -> dict:                           # the Results document (section 5)
```

Rules: the kernel mutates state; policies choose among offered options; every random draw uses
`numpy.random.default_rng(seed)`; calibration is read from `ctx.calibration_dir`; future realized case activity never enters process predictions at cutoff `t0`; actual incoming orders are
supplied as exogenous inputs. Workforce reference outcomes are used only for scoring and display.

## 3. Run folder (`runs/<id>/<scenario>/<run_id>/`)

`trace.parquet` columns: `tick` (hours since start), `sim_time`, `agent_id`, `role`, `org_unit`, `case_id`,
`activity`, `action_type` (start, complete, handoff, wait, decide, arrive, state, message, exogenous), `duration_h`,
`wait_h`, `provenance` (simulated, replayed, exogenous), `attributes` (JSON: rationale, states, option chosen).

Companions: `config.json` (scenario + seed), `summary.json` (`RunSummary` with a `headline` dict of key numbers),
`metrics.json` (workforce: arms, attrition, satisfaction, take-up, weekly cumulative attrition), `twins.json`
(workforce: `{n, trait_keys, twins: [{agent_id, role, org_unit, team_id, arm, seat, profile, traits, offered,
eligible_days, wfh_days, quit_week, final_states, final_quit_hazard_week}]}`). `latest.json` per scenario points at
the newest run.

## 4. `data/normalized/summary.json` (Overview details)

```json
{"title": "...", "period": "2018-01-01 .. 2019-01-31",
 "facts": [{"label": "...", "value": 251734, "unit": ""}],
 "org": {"units": [...], "roles": [{"id", "label", "headcount", "onet_code"}], "systems": [...]},
 "charts": [chart]}
```

Chart object (rendered by `ui/components/chart.js`): `{id, type: bar|hbar|line|scatter, title, x_label, y_label,
x: [...], series: [{name, y, x?, color?, band?: [lo, hi], point?, dashed?, outlined?, source?}], note, y_min?, y_max?, x_log?, y_log?}`.
`x_log`/`y_log` switch an axis to a logarithmic scale; a scatter series may carry its own `x` values.

## 5. Evaluation and results

`runs/<id>/evaluation.json`: `{instance, generated, scenarios, protocol, headline: {metric id: {label, simulated,
actual, baseline, unit, better, interval, covered_90, within_trial_ci95}}, metrics: [...], charts: [chart],
scenario_comparison: [{scenario, title, <kpi>: value}]}` plus world-specific blocks. Process worlds whose protocol
names `before_cutoffs` and `change` add `periods: {before, after: {cutoffs, runs, staff_active, arrivals,
population, metrics: {id: {simulated, actual, interval}}}}` and `change: {label, description, staff_before,
staff_after, ratio}`. There is no version or history field; the file is overwritten on every evaluation.

`GET /api/instances/{id}/results` (from `results_view`): `{instance, company, scenarios: {baseline: {id, title,
short_title}, alternative: {...}}, sources: [{id: actual|baseline|alternative, label, kind, kind_label, short,
scenario, runs, note}], metrics: [{id, label, unit, better, values: {source: value}, intervals: {source: [lo, hi]},
note}], effects: [headline entries], charts: [chart with series.source], hero: {kicker, stats: [{label, value,
unit}], claim, chart, comparison?: {title, change, reference_note, stats: [{label, value, unit, note?}],
chart: <chart object>, accuracy}, alternative?: {kicker, stats, text, chart?}}, narrative: {takeaways, sections}, plugins:
[{id, title, url}], evaluation: {generated, protocol}}`. Baseline values come from `evaluation.json`; alternative
values are means over the current evaluation cohort with 5th-95th percentile ranges. The hero is
also attached to each instance in `GET /api/instances` for the landing page. `hero.comparison` supplies the primary
reference / actual impact / simulated impact comparison and computed error. Its chart uses `source: actual|baseline`.
The workforce reference is the contemporaneous control; the process reference is the saved historical rate, not
a causal no-change counterfactual. No run values are changed by this presentation layer.

Evaluation also records `run_ids: {scenario: [run_id]}`. Results and reports use only that cohort; unrelated runs never enter an alternative comparison. Process `periods.before` has `runs: 0`, `observations`, and actual-only metrics. Before horizons must end before `change_date`.

Process `business_validation` contains `{id, windows: [{cutoff, actual, simulated, baselines}], simulation_mae, baseline_mae, best_baseline, beats_best_baseline, error_reduction_pct}`. MAE averages absolute errors over cutoffs after averaging seeds within each cutoff. `calibration_window` records the final pre-policy fit. Protocol `workers` controls independent process workers without changing protocol order.

Market evaluation (`orgsim/worlds/market.py`) adds `windows: [{cutoff, n_apps, censored_pct, company_tokens_wape, company_spend_wape,
company_tokens_mdape, direction_hit: {simulation, <comparator>: value}, coverage90, levels: {top_tokens, top_spend, market_tokens,
prog_leader_share: {before, actual, simulation, interval?, <comparator>}}, by_horizon: {<weeks>: {simulation, <comparator>}},
by_class: {<steady|recurring|burst>: {n, simulation, <comparator>}}, model_shares: {<segment>: {distance, new_share}}, launch_rank?,
spend_formula_wape?, run_ids}]`, `accuracy` (the same measures averaged over windows, with `best_baseline` and `error_reduction_pct`;
`by_horizon`, `by_class`, `model_shares`; with a language-model buyer also `launch_rank`, `launch_rank_held_out` and
`company_spend_wape_formula`), `business_validation` for the three totals, `comparator_labels` and `scatter` (one row per company
prediction). Market run summaries carry per-app `tokens`/`spend_usd` (this run) and `tokens_central`/`spend_central` (the central
path, the point prediction), segment prices and model mixes; with a language-model buyer also `segment_mix_end_rule`,
`spend_central_formula`, `buyer` (calls, cache hits, spend) and `launch_scores`.

Adoption evaluation (`orgsim/worlds/adoption.py`) reads `data/normalized/series.parquet` (`group, period, date, value, se`;
periods are consecutive integers) and `groups.parquet` (`group, label, modelled?, scored?`), and `calibration/adoption.yaml`
(`outcome: share|displaced`, `normalize` (shares of one whole), `aggregate_group`, `grid`, `default_spec`, and for displaced outcomes `change: {period,
season_periods, fourier, baseline_periods}`). The protocol names `cutoffs` (a list of periods or `{first, last, step}`),
`blocks: [{id, label, from, to}]` (horizons in periods; shares are averaged, volumes summed), `headline_blocks`,
`comparators`, `scale` and `unit`; the first quarter of the cutoffs (at least two) is the development set
(`ADOPTION_CUTOFFS=dev` runs only those). It writes `windows: [{cutoff, cutoff_date, selection, spec, blocks: {<block>: {mae:
{simulation, <comparator>}, mean_actual, n, coverage90, target_from, target_to}}, run_ids}]`, `accuracy: {all|dev|held_out:
{<block>|headline: {mae, mean_actual, n_predictions, best_baseline, error_reduction_pct, accuracy_pct, coverage90?}}}`,
`by_group` (held-out, headline blocks), `rows` (one per cutoff, block and scored group with every prediction and the 90%
range) and `comparator_labels`. Adoption run summaries carry per-group `central`/`run` (outcome scale) and
`central_share`/`run_share`, plus `calibration`. `scripts/build_adoption_validation.py <id>` writes
`docs/validation_<id>.md` and `runs/<id>/value_inputs.json` (each figure with its path inside `evaluation.json`).

Workforce evaluation adds `paired_comparison` and `paired_effects` for matching scenario seeds. Metric `paired_baseline` and chart-series `paired_y` / `paired_band` supply that subset in the alternative panel, while the validation panel uses the full evaluation ensemble. Point predictions are means; `point_path` may select the expected-quit estimator while the realized `path` supplies predictive intervals. The expected-quit estimator is the accumulated hazard while at risk, not an individual probability.

A workforce protocol may name a `kind`, which selects its own scoring module. Both kinds take their other predictions from the instance's `evaluation/comparators.py`. They also write `runs/<id>/value_inputs.json`: `{instance, evaluation, generated, figures: [{name, path, value}]}`, where each `path` is a dotted path inside `evaluation.json`.

- **`kind: experiment`** (`orgsim/worlds/workforce_experiment.py`; `comparators.compute(ctx) -> {id: {label, description, values: {metric id: value}}}`). The evaluation contains:
  - `metrics` and `metric_index`: `{id, label, kind: level|did|did_pct|attrition_level|attrition_effect, unit, simulated, interval, actual, actual_se, before, comparators, comparator_errors, best_comparator, error_reduction_pct, accuracy_pct?}`;
  - `headline`, `comparators`, `comparator_labels`, `scenario_comparison`, `population` and `charts`.
- **`kind: forecast`** (`orgsim/worlds/workforce_forecast.py`; `comparators.compute(ctx, cutoff, months, groups) -> {id: {label, description, pred: DataFrame(group, month, n)}}`, plus `comparators.actual(ctx, cutoff, months)` for scoring). The evaluation contains:
  - `windows`: `[{cutoff, role: development|held_out, months, n_groups, headcount_start, scores: {source: {group_month_wape, group_total_wape, total_error_pct, total_month_wape, actual_total, predicted_total}}, best_comparator, error_reduction_pct, by_type, monthly, groups}]`;
  - `accuracy`: `{held_out, development, all}`;
  - `business_validation`, `scatter` and `scenario_comparison`.

Optional workforce-world blocks are documented in the module docstring of `orgsim/worlds/workforce.py`:
- dynamics `constants`, `series`, `measures` and `offers`;
- cohort twins via a `headcount` column, with competing `hazards` given `monthly:` rates;
- scenario `events`, `offers`, `count_by`, `stock`, `population_file` and `twins_sample`.

Run metrics then add `measures` (`{name: {all: by arm, weekly}}`) and, for cohort twins, `separations` (`{by, groups, months, kinds, expected, realized, headcount_start, pending_at_end}`).

The story's `reference_actual` is the office-only group observed alongside the hybrid group, used to measure policy impact. `before_actual` contains pre-policy observations, including the published division-level historical attrition aggregate; it is distinct from the later randomized employee cohort. Missing pre-policy outcomes are null.

Optional `story.comparator_explanation` contains `{paragraphs, formula, sources: [{label, url}]}` and explains the other prediction methods beside the comparison. Optional `story.level_comparison` contains `{label, unit, actual, simulated, predictions: [{label, value}]}` to distinguish an overall outcome from the policy impact. Trip.com's historical inputs and calculation are sourced in `manifests/pre_policy.yaml` and `evaluation/comparators.yaml`; `comparators` in its evaluation records the calculated values and provenance.

The Results page displays `level_comparison` and effect comparisons together in one **Actual outcomes and predictions** table. Rows state whether they show a group outcome or the difference between groups; optional metric `effect_label` names the latter. Uncertainty and subgroup cards open inside that same section.

Reader-facing labels use **Actual outcome**, **Simulation prediction**, and **Other prediction**. Policy impact means the hybrid group's outcome minus the office-only group's outcome during the same period. The words engine, forecast, trial and ITT are reserved for internal identifiers or original source titles, not product labels. Internal API keys remain stable.

Results also include `explorations: [{id, title, description, state: missing|stale|ready,
interventions, note, assumption_basis, sources, generated?, runs?, seeds?, cutoffs?,
metrics: [{id, label, unit, better, baseline, alternative, delta, delta_range}], review_hours?, rework_hours?}]`.
`delta_range` contains the 5th and 95th percentiles of matched differences, not a
confidence interval for real-world AI efficacy. These comparisons have no actual AI outcome column.

`runs/<id>/explorations.json` maps scenario IDs to saved configurations, fingerprints,
and pairs of baseline/alternative run IDs and headlines. The model fingerprint
includes world/kernel/policy/scenario code, calibration, bindings, seat policies, and
input tables. The reference evaluation is also hashed. Procurement reference reuse
requires matching model, evaluation, and baseline configuration fingerprints;
otherwise the comparison reruns the reference. Invalidated results return
`state: stale` with no metrics. Reports omit invalidated exploration sections.
Run headlines include `workload: {human_hours, unassisted_hours, review_hours, rework_hours}`;
workforce twin records include individual workload totals and `ai_assisted`.

## 6. Report (`instances/<id>/reports/report.json`)

`{title, subtitle, generated, takeaways: [one sentence each, with the number], sections: [{heading, body (markdown),
charts: [chart id], metrics: [metric id]}], charts: [chart], metrics: [as in evaluation]}`. Built by
`reports/build_report.py` from the evaluation and run outputs; no hedging, no version or iteration language.

## 7. Detailed views (`instances/<id>/ui/pages.json`)

`[{"id": "process-map", "title": "Process map", "entry": "process-map.html", "icon": "flow"}]`. Each entry is a
self-contained page served at `/instances/<id>/ui/<entry>` and embedded in Results as an iframe. It may call the
same API and should load `/ui/theme.css`.

## 8. Ontology and data endpoints

- `GET .../ontology` bindings graph merged with the O*NET subgraph (`?tasks=1` adds tasks); `GET .../ontology/schema`.
- `GET .../ontology/concepts`: `{schema, concepts: [{type, description, layer: bound|onet|runtime, count, used}],
  relations: [{source, type, target, description, count, used}], layers, stats}`.
- `GET/PUT .../ontology/bindings`: raw bindings; PUT validates and returns `{saved, problems}`.
- `GET .../people?offset&limit&q&sort&desc&group`: paged person table (`columns` carry labels);
  `GET .../people/graph`: `{groups: [{id, type, kind, label, parent, size}], links, person_links: [{type, basis,
  count}], notes, excluded_from_behavior}`; `GET .../people/{pid}/ego?limit`: a typed graph of one person's
  neighbourhood plus `person` and `connections` (`same_manager` teammates or weighted `hands_off_to` partners).
  Reads only normalized data and bindings, never runs.

## 9. Scenarios, runs, insights

- `GET /api/instances` includes all named `alternatives` for the landing cards;
  `alternative` retains the primary alternative for existing clients.
- `GET .../scenarios` lists `{id, title, short_title, description, extends, file, role}`; `GET/PUT .../scenarios/{sid}`
  resolved scenario; `GET/PUT .../seats`.
- `GET .../runs`; `POST .../runs {scenario, seed}` launches a run in the background;
  `GET .../runs/{sid}/{run}/summary|config|metrics|trace|timeline|agents|twins`.
- `POST .../explorations {scenario}` launches a named additional alternative and returns
  `{job_id, scenario, state: queued, pid}`. `GET .../exploration-status` returns
  `{job_id?, scenario?, state: idle|queued|running|complete|failed, generated?, error?}`.
  The same operation is available as `orgsim explore <id> --scenario <sid>`.
  AI comparisons require unchanged reference policy, staffing, and time period;
  only AI interventions and trace sampling may differ.
- `GET .../insights` returns `runs/<id>/insights.json`; `POST .../insights {n, model}` rebuilds it:
  `{generated, method: template|llm:<model>, note, scenarios: {<named role>: {scenario, title, run_id,
  n_interviews, groups, sentiment_basis, questions, interviews: [{agent_id, role, group, outcome, profile, facts,
  topics, sentiment, qa: [{metric, question, answer, topics, sentiment}]}], topics: [{id, label, count, share,
  by_group}], sentiment: {distribution, by_group}, key_insights}}, comparison: {sentiment, topics, key_insights}}`.

The full endpoint list is the docstring of `orgsim/server/app.py`; interactive docs at `/docs` when serving.


## 10. Application ports and task-planner extensions

`orgsim/application/ports.py` defines structural Python protocols. The composition
root binds `SimulationService` to a `SimulationModel`, `RunRepository`,
`OutcomeScorer` and `ResultsPresenter`. A run begins with `RunRepository.begin`,
passes its sink to `SimulationModel.run`, then publishes the summary on success or
calls `abort` on failure. Existing world modules remain supported through
`orgsim/adapters/instances.py`, including their internal batch evaluators. CLI,
HTTP Results and alternative execution use this service without changing their
existing file/API shapes.

The separate authored workflow uses `DataSnapshot[Observation]`,
`TaskPlanner[Observation, Plan]` and `DecisionRepository`. SDK types do not appear in
these contracts. JSON models in `orgsim/workflow/contracts.py` forbid unknown
fields, non-finite floats and invalid ranges; timestamps require a timezone.

| Object | Required information |
|---|---|
| `WorkflowSpec` | `as_of`, `records`, `resources`, `horizon_h`; integer `seed` defaults to 1 |
| `TaskRecord` | `task`, `effective_at`, `available_at`; neither timestamp is inferred |
| `Task` | `id`, `skill`, positive `work_h`, `review_h`, `rework_h`; optional `arrival_h`, `error_probability`, `depends_on` |
| `Resource` | `id`, `kind` (`human` or `ai`), `skills`; positive integer `capacity`, positive `speed`, nonnegative `hourly_cost`, `error_multiplier` |
| `Observation` | `as_of`, visible `tasks`, scenario `resources`, `horizon_h`; no actual outcomes or realized quality draws |
| `Proposal` | `command_id`, `task_id`, `assignee_id`, `reviewer_id`, `correction_assignee_id`; optional `rationale` |
| `Plan` | `proposals`, `model`, `prompt_version`; optional `input_tokens`, `output_tokens`, `planning_cost`, `fallback` |

`RecordSnapshot.read(as_of)` admits only records whose effective **and** availability
times are at or before the cutoff. For a task with multiple versions, it selects the
latest available version, breaking ties by effective time; conflicting versions
with identical timestamps fail. Missing dependencies and dependency cycles fail.
Resources and future announced arrival hours are explicit scenario assumptions.
This contract does not automatically repair availability issues in legacy datasets.

A planner exposes `identity: dict[str, str]` and
`plan(observation: Observation) -> Plan`. Identity must describe the adapter,
policy/model/prompt/settings that determine behavior. `command_id(observation,
task_id)` supplies the stable ID. The kernel requires exactly one assignment for
every visible task, qualified workers and human review/correction. Identical
repeated commands are deduplicated; conflicting reuse, incomplete coverage and
assignments for a different snapshot fail before scheduling. Planners cannot
change task effort, dependencies or resource capacity. Unknown planning usage/cost
is null; the deterministic fixtures explicitly record zero.

`load_planner` supports `rule`, optional `langgraph`, and an installed
`module:factory`. An external factory receives `checkpoint_dir: Path` and its
JSON options, returning the same planner contract. This is trusted local CLI
configuration, not an HTTP code-loading endpoint. A Microsoft Agent Framework
adapter can be implemented behind it; none is bundled. See
[implementing an adapter](task-planners.md#implement-an-adapter).

`DecisionRepository.read(kind, key)` and `write_once(kind, key, value)` persist
portable JSON. Identical writes are idempotent; different content at an existing
key is an error. The local SQLite schema stores:

- `decision`: observation, planner identity and accepted plan, keyed by their
  observation/identity digest; committed before simulation execution.
- `run`: run key, decision key and deterministic kernel result (seed, kernel
  identity, applied command IDs, events and outcomes). Its key includes decision,
  seed and kernel identity.

`runs/workflow/decisions.sqlite` owns this journal. `langgraph.sqlite` holds only
framework execution checkpoints. A completed run also has `<run-key>.json` with
its authored-exploration label, planner identity and kernel result. These paths
are ignored by Git. No existing instance's evaluation or artifacts are overwritten.
`orgsim workflow --replay <run-key>` recomputes the stored decision and checks exact
result equality without loading a planner. Concurrent conflicting decisions fail;
exactly-once execution of external provider calls is not guaranteed.

Kernel event fields are `operation_id`, `task_id`, `stage` (work/review/correction),
`resource_id`, `slot`, `start_h`, `end_h`, `performed_h`, `wait_h`, and `complete`.
Time is continuous operating hours. `end_h` may exceed the horizon, but
`performed_h` and costs are limited to work actually performed within it.
Outcome fields are `completed_tasks`, `throughput_per_hour`, `mean_elapsed_h`,
`staff_effort_h`, `correction_rate`, and `service_cost`. Mean elapsed time is among
completed tasks; correction rate is among reviewed tasks; both are null with no
eligible observations. Service cost uses assumed AI resource rates; human payroll
and planning API cost are not included. Planning usage remains in the decision
metadata. Every realized correction consumes human effort and is assumed to fix
the error; no residual quality or calibrated organizational effect is claimed.

## 11. Public snapshots and release archives

`public-data/index.json` declares `schema_version: 1`, the capture time, source
commit, instance catalog, required O*NET occupations and SHA-256 hashes for each
`<instance>.json`. Each instance document records its evaluation checksum and a
`responses` mapping keyed by instance-relative GET routes (for example `/results`,
`/scenarios/baseline`, `/insights` and `/ontology/concepts`). Existing response shapes
are preserved. `/runs` includes only ID/scenario/completion metadata for scenario
counts; individual traces, twins, people endpoints and table rows are not exported.

`scripts/export_site.py snapshot` reads prepared local application responses and
rejects stale/missing AI alternatives. `build` verifies the index and copies only
listed instance snapshots with the shared UI. Its generated HTML sets
`<meta name="workcast-mode" content="static">`. The API adapter resolves relative
snapshot URLs at either a project subpath or domain root and rejects non-GET calls;
fixture mode cannot override static mode. No Python backend is deployed.

Release `snapshot.json` separately records source commit/tag, source/license
manifests and an asset list. Each asset has its name, kind (`data` or `runs`), byte
count, SHA-256 and member-path map with sizes and hashes. Restore accepts only
regular files inside the declared dataset/run roots, rejects traversal/links and
checks every member before copying. Existing non-identical files are never
overwritten. The committed compact manifest pins the release manifest checksum;
full inventories and archives stay attached to the GitHub release.
