# WORKCAST simulation platform: guide for agents working in this repository

Read this first. It says what the platform is, the rules that must hold, where things live, and how to verify work.
Detailed references: `docs/architecture.md` (how it is built), `docs/contracts.md` (file and API shapes),
`docs/ui.md` (page by page), `docs/validation.md` (the two instances, their data, protocols and results),
`docs/literature/foundations.md` (what the design borrows from and the sources behind the priors).

## The framing every instance follows

1. **Actual outcomes and predictions.** Observed before, the change, then actual outcomes alongside other
   predictions and simulation predictions. Before data may calibrate the simulation; neither group's
   post-change outcomes may do so. Never present a simulated "before": only the after period is scored.
2. **Alternative actions and their impact.** Named alternatives the company did not try, simulated against the simulation
   of what actually happened.

## What this is

An organization-simulation platform by Emergent Science (product name WORKCAST). A real company is rebuilt as a
simulation: its people as digital twins, its work process on an hourly clock. For each **instance** (one company,
one dataset) the platform runs a **baseline** that reproduces what actually happened, scores it against the real
outcome, then runs **alternative scenarios** the company did not try, and finally **interviews the simulated
agents** about the key metrics. The audience is mid to higher management playing out potential decisions, including investor demos. Every first
screen must show the actual change, reference condition, observed impact, simulated impact and prediction error.
Alternatives follow; detailed metrics remain available on selection.

Two instances exist and run end to end:

- `trip`: Trip.com's 2021 randomized hybrid-work experiment (1,612 employees as twins; predictions of the policy's
  effects, scored against observed outcomes; alternatives "hybrid for everyone" and an employee AI assistant).
- `bpi19`: a multinational's purchase-to-pay process (BPI Challenge 2019 event log, 251,734 purchase-order items;
  the simulation predicts two-week horizons after the September 2018 workforce expansion, with the observed before period as reference; alternative "no
  expansion" and an AI invoice assistant).

## Rules that must hold (do not relax these without the user)

1. **Every number is computed.** Nothing in the UI, reports, insights or docs is typed in by hand. Reports are built
   by `instances/<id>/reports/build_report.py` from `runs/<id>/evaluation.json` and run outputs; the landing-page and
   Results hero blocks come from `results_view(ctx)`; insights come from each agent's simulated record.
2. **Nothing is fitted on the outcome it is scored against.** Trip.com: every behavioral parameter in
   `calibration/priors.yaml` has a central value, a range and a cited independent source; post-change outcomes are
   used only for scoring and display. BPIC 2019: select the specification with January-June fitting and July-August validation; refit the selected model on all data strictly before September 1. The user permits pre-policy calibration but forbids either group's post-policy data as calibration. Only after-change predictions are scored; future case activity is withheld at each cutoff, while actual incoming orders are supplied. Trip results are retrospective: the inherited prior revision log records prior outcome-based comparison, so do not claim a pristine prospective holdout.
3. **No iteration or version talk, and no old results.** No "v4", "best of three rounds", evaluation history or
   changelog text anywhere in the product or the docs. `runs/<id>/evaluation.json` is the only scored result; old
   result files are deleted, not archived. The only provenance kept is the sourced `revision_log` inside
   `calibration/priors.yaml`.
4. **Protected demographics never drive behavior.** Gender is in the data and shown in tables, but it enters no
   behavioral function, no prior and no prompt.
5. **Kernel authority.** The kernel (clock, capacity, constraints, state dynamics) mutates state; a seat policy (rule,
   hosted LLM or local model) only chooses among the options the world offers. Swapping the model in a seat is a
   configuration change in `policies/seats.yaml`.
6. **Each instance is self-contained.** Everything a viewer needs (ontology, data, scenarios, runs, results, insights)
   lives inside the instance's tabs. The landing page is only the instance picker. Nothing lives "between" instances.
7. **Two tracks stay separate.** Real-data validation (these two instances) and any AI-as-CEO or authored-firm
   roleplay are never mixed in the same page, report or claim.
8. **Simulated interviews are labelled as simulated.** Insights say that no real person said any of it.
9. **Do not commit to git unless asked.** Run outputs (`runs/`), instance data (`instances/*/data/`) and shared
   reference data (`data/`, except manifests) are git-ignored and reproducible.

## Layout: where to put things

```
CLAUDE.md, README.md          this guide; product summary and quickstart
docs/                         setup, architecture, contracts, ui, validation; literature/foundations.md
orgsim/                       the platform package (Python 3.12, FastAPI)
  instances.py                instance discovery (InstanceContext: paths, meta, yaml())
  kernel/                     clock (hourly ticks), scheduler, capacity pools, World protocol
  ontology/                   schema.py (concepts + relations with definitions), bindings.py (instance bindings -> graph),
                              onet.py (O*NET 31.0 loader), people.py (data graph: people and connections),
                              system.py (concept graph as used by one instance)
  policies/                   seat adapters: rule, llm (Anthropic), local (OpenAI-compatible); registry
  scenarios/                  loader (extends/deep-merge, named alternatives); shared AI workload assumptions
  worlds/                     one module per world type: process.py, workforce.py (+ survival.py);
                              each has World, evaluate(ctx, ids) and results_view(ctx)
  evaluation/                 metrics, Markov baselines, results.py (shared results-view helpers)
  insights/                   interview.py (simulated interviews, topics, sentiment, key insights)
  store/                      run writer/reader (parquet trace, summary/metrics/twins json), run listing
  server/app.py               the API (docstring lists every endpoint) and static UI serving (no-cache headers)
  cli.py                      orgsim instances|validate|ingest|run|evaluate|explore|insights|demo|serve
ui/                           build-free shell: index.html, theme.css (tokens), app.js (router), api.js,
                              components/ (ui, chart, grid, graph, kpi, markdown), pages/, assets/logo.svg,
                              dev/smoke.html (+ fixtures)
instances/<id>/               one company: instance.yaml, manifests/, ingest/, ontology/bindings.yaml,
                              policies/seats.yaml, calibration/, scenarios/, evaluation/protocol.yaml,
                              reports/build_report.py (+ report.json), ui/ (optional detailed views), data/ (ignored)
instances/_template/          what a new instance needs
data/                         shared reference data (O*NET 31.0), manifests/
runs/<id>/                    run folders per scenario, evaluation.json, insights.json (ignored)
tests/                       core, fidelity, and repository-tool checks; data marker for local dataset dependencies
```

Rules of thumb: platform code never contains instance logic; if two instances could use it, it belongs in
`orgsim/` or `data/`; if only one world uses it, it belongs in that instance folder. World-type-specific computation
(metrics, results view, interview facts) goes in the world module, not in the server or the UI.

## How to do common things

- **Set up**: `uv sync --locked --extra dev --python 3.12`, then `uv run python scripts/download_data.py`.
  See [setup](docs/setup.md) for acquisition, reproduction and upload instructions.
- **Run everything**: `.venv/bin/orgsim demo` (ingest, run every scenario, evaluate, insights; tens of minutes). Per step:
  `orgsim ingest <id>`, `orgsim run <id> --scenario <sid> --seeds 1,2,3`, `orgsim evaluate <id>`,
  `orgsim insights <id>`, then `.venv/bin/python instances/<id>/reports/build_report.py`.
- **Serve**: `.venv/bin/orgsim serve --port 8000` then http://127.0.0.1:8000. Restart your server after Python changes,
  or use `--reload` during development. Check which process owns the port before stopping it.
  Never put the literal text `orgsim serve` in a command that also runs `pkill -f`/`pgrep -f` (it matches itself).
- **Add an instance**: copy `instances/_template`, write `instance.yaml` (`company`, `problem`, `situation`,
  `data_used`, `intro`, `scenarios: {baseline, alternative, additional_alternatives?}`, `protocol_line`), an ingest that writes `data/normalized/*` and
  `summary.json`, bindings validated by `orgsim validate <id>`, `calibration/`, `evaluation/protocol.yaml`,
  `scenarios/baseline.yaml` + named alternatives with `short_title`, and a report builder. The UI needs no change.
- **Add a world type**: a module in `orgsim/worlds/` with `World`, `evaluate`, `results_view`, registered in
  `orgsim/worlds/__init__.py`; a people builder in `orgsim/ontology/people.py`; an interview builder in
  `orgsim/insights/interview.py`.
- **Change the UI**: pages are ES modules in `ui/pages/`; tabs and order in `ui/app.js` (`CORE_PAGES`); design tokens
  in `ui/theme.css` (dark by default, zinc + emerald, logo and wordmark in `index.html`). No build step, no node.
  The server stamps module URLs with a version and sends no-cache headers, so edits show after a normal reload.
- **Change a contract** (file shape, endpoint): update `docs/contracts.md` in the same change.

## How to verify (do all three before saying something works)

1. `.venv/bin/python -m pytest tests -q` (requires normalized data and both evaluations).
   A fresh checkout can run `pytest -m 'not data'`; do not describe that subset as the full suite.
2. UI smoke harness against the live server (prints `DONE errors=0`):
   `chrome --headless --disable-gpu --no-sandbox --window-size=1400,1000 --virtual-time-budget=120000 --dump-dom
   "http://127.0.0.1:8000/ui/dev/smoke.html?instance=trip"` and read the `#log` element; repeat for `bpi19`.
3. Look at the pages: `chrome --headless --disable-gpu --no-sandbox --window-size=1500,1250 --virtual-time-budget=15000
   --screenshot=<png> "http://127.0.0.1:8000/#/trip/results"`, then open the PNG. Replace `chrome` with an available
   Chromium-compatible executable; `--no-sandbox` is only needed in environments that require it.

## Writing for the product

Plain language: the actual change first, then reference condition, observed impact, simulated impact and error.
Do not hide the evidence of accuracy behind a disclosure. Alternatives follow the actual-data comparison. Extra
metrics and supporting detail open on selection. Label a contemporaneous control as a control, not a pre-period;
label historical period differences as such, not as isolated causal effects. Keep editing in Ontology (relationships), Data (digital twins and objects),
and Scenarios (alternative configurations). Results, Scenarios, Data and Ontology stay visible; inspection pages
live under More. Do not add methodology or model-history commentary to the demo. Prefer removing to adding. Label simulated sources as simulated and ground truth as actual data. Use the
scenario `short_title` in tables. Use "Actual outcome", "Simulation prediction", and "Other prediction";
use plain group names, not engine, forecast, trial or ITT in reader-facing labels. Internal identifiers stay stable.
