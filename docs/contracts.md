# Contracts

The agreements between the platform package `orgsim/`, the instances under `instances/` and the UI under `ui/`.
Change a contract here in the same change that alters it.

## 1. Instance folder

`instances/<id>/instance.yaml` must include `id`, `title`, `company`, `problem` (the business question, one
sentence, shown as the card title), `situation` (two sentences: what the company did), `data_used` (one or two
sentences: the dataset and what it records), `intro` (one concise paragraph: what is simulated and what the
alternative asks), `world_type`
(`process`, `workforce` or `market`), `world` (one paragraph), `clock.tick: 1h`, `clock.coverage`,
`scenarios: {baseline: <id>, alternative: <id>}`, `protocol_line` (one sentence on how the result is kept honest)
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

The story's `reference_actual` is the office-only group observed alongside the hybrid group, used to measure policy impact. `before_actual` contains pre-policy observations, including the published division-level historical attrition aggregate; it is distinct from the later randomized employee cohort. Missing pre-policy outcomes are null.

Optional `story.comparator_explanation` contains `{paragraphs, formula, sources: [{label, url}]}` and explains the other prediction methods beside the comparison. Optional `story.level_comparison` contains `{label, unit, actual, simulated, predictions: [{label, value}]}` to distinguish an overall outcome from the policy impact. Trip.com's historical inputs and calculation are sourced in `manifests/pre_policy.yaml` and `evaluation/comparators.yaml`; `comparators` in its evaluation records the calculated values and provenance.

The Results page displays `level_comparison` and effect comparisons together in one **Actual outcomes and predictions** table. Rows state whether they show a group outcome or the difference between groups; optional metric `effect_label` names the latter. Uncertainty and subgroup cards open inside that same section.

Reader-facing labels use **Actual outcome**, **Simulation prediction**, and **Other prediction**. Policy impact means the hybrid group's outcome minus the office-only group's outcome during the same period. The words engine, forecast, trial and ITT are reserved for internal identifiers or original source titles, not product labels. Internal API keys remain stable.

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

- `GET .../scenarios` lists `{id, title, short_title, description, extends, file, role}`; `GET/PUT .../scenarios/{sid}`
  resolved scenario; `GET/PUT .../seats`.
- `GET .../runs`; `POST .../runs {scenario, seed}` launches a run in the background;
  `GET .../runs/{sid}/{run}/summary|config|metrics|trace|timeline|agents|twins`.
- `GET .../insights` returns `runs/<id>/insights.json`; `POST .../insights {n, model}` rebuilds it:
  `{generated, method: template|llm:<model>, note, scenarios: {baseline|alternative: {scenario, title, run_id,
  n_interviews, groups, sentiment_basis, questions, interviews: [{agent_id, role, group, outcome, profile, facts,
  topics, sentiment, qa: [{metric, question, answer, topics, sentiment}]}], topics: [{id, label, count, share,
  by_group}], sentiment: {distribution, by_group}, key_insights}}, comparison: {sentiment, topics, key_insights}}`.

The full endpoint list is the docstring of `orgsim/server/app.py`; interactive docs at `/docs` when serving.
