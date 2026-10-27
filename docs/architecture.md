# Architecture

How the WORKCAST simulation platform is built. For file and API shapes see `contracts.md`; for the pages see
`ui.md`; for the instances and their results see `validation.md`.

## 1. One platform, many instances

The platform is the product; an instance is one company turned into a simulated world. The platform never contains
instance logic. An instance is a folder under `instances/<id>/` holding its data, ontology bindings, seat policies,
calibration, scenarios, evaluation protocol and report builder. The three world types in use are:

- **workforce** (`orgsim/worlds/workforce.py`): a population of employees, each a digital twin with a fixed trait
  layer and weekly latent states (job satisfaction, work-life balance, commute burden, attachment), reacting to a
  policy over time. Used by `trip`.
- **process** (`orgsim/worlds/process.py`): work items flowing through activities performed by role pools under
  capacity and process constraints, with a payment-run calendar and same-person continuity. Used by `bpi19`.
- **market** (`orgsim/worlds/market.py`): companies whose AI workloads run on models at published list prices. Each
  company has a token volume, a growth path and a persistence class (one-off job, recurring, steady product); each
  use-case segment holds workload agents that choose among the models listed that week. Calibrated at every cutoff from
  backtests that end before it; the central path (every shock at its median) is the point prediction and the runs give
  the ranges. Used by `openrouter`.

A world type exposes three functions: `World` (the simulation), `evaluate(ctx, scenario_ids)` (scores the
baseline against ground truth and writes `runs/<id>/evaluation.json`) and `results_view(ctx)` (the document the
Results tab renders, including the hero block).

## 2. Kernel and policies

The kernel owns time, capacity and state: an hourly clock, a scheduler, capacity pools per role, and the latent-state
dynamics declared per instance. Policies only choose. Every decision point offers the seat an `Observation` with
options and prior-driven weights (work from home or office on an eligible day; stay or quit this week; the next step
for a purchase-order item), and the seat's adapter returns one option:

- `rule`: draws from the offered weights (transparent, deterministic given the seed);
- `llm`: a hosted Anthropic model reads the same observation, including the twin's profile and states, and chooses;
- `local`: an OpenAI-compatible local server.

Failures fall back to the rule policy and the fallback is recorded in the trace. `policies/seats.yaml` maps seats
(role ids) to adapters, so swapping a model is configuration.

## 3. Digital twins (workforce worlds)

Each employee carries the real covariate vector of one experiment participant. Once per run a trait layer is computed from
those covariates and the sampled priors: baseline satisfaction, baseline quit hazard, a work-from-home preference
trait that drives both take-up and the value of each home day, commute. A text profile is rendered from the traits
and offered to every seat. Weekly, the kernel updates the latent states with inertia, team comparison (employees not
offered the policy while teammates are), and an amenity channel; the quit hazard combines satisfaction, commute,
the direct value of the arrangement and attachment. Every run writes `twins.json` with traits, final states and
outcomes per twin; the Runs page shows the twin card and Insights interviews them.

The design follows the finding (see `literature/foundations.md`) that employee states are trait-like: fidelity comes
from the fixed trait layer and kernel-owned dynamics, not from per-decision language-model reasoning.

## 4. Ontology

`orgsim/ontology/schema.py` defines the concepts (Organization, OrgUnit, Person, Role, Occupation, GWA, IWA, DWA,
Task, Activity, WorkItem, Artifact, System, Capability, Location, ExternalActor, Message, Policy, Event, LatentState)
and the relations they may have (has, member_of, part_of, has_role, bound_to, performs, maps_to, located_at,
same_manager, hands_off_to, affects, has_state, ...), each with a one-line definition. Roles are bound to O*NET-SOC
occupations and activities to O*NET detailed work activities, so roles in different companies share a vocabulary.
`bindings.py` turns an instance's `ontology/bindings.yaml` into a typed graph; `system.py` reports which concepts
and relations an instance uses and how many; `people.py` builds the data graph (who the people are and who each is
connected to: teammates in workforce worlds, hand-off partners in process worlds).

## 5. Evaluation and results

Each instance has `evaluation/protocol.yaml` (what is scored, against what, with which baselines). `evaluate()`
runs only the after-change predictions, compares to reference outcomes and non-simulation predictors, and writes metrics, intervals, charts
and matching-cutoff/seed scenario comparisons. Before periods are observed data only. Run IDs pin the display cohort; per-window business errors prevent cancellation across cutoffs. `results_view()` assembles the Results document: actual outcomes, non-simulation comparison methods,
simulation predictions, and alternative simulation predictions, key metrics with ranges, treatment effects (workforce), trajectories, the report
narrative, and the hero block. Reports (`reports/report.json`) are generated by each instance's `build_report.py`
from the evaluation and run outputs; the narrative appears under Results.

## 6. Insights

`orgsim/insights/interview.py` interviews a stratified sample of agents from the latest baseline and alternative
runs about the key metrics. Facts come from the agent's simulated record (twin traits, states, decisions; or a role
pool's utilization, waits and exceptions). Answers are rendered by a deterministic template voice, or by a hosted
model over the same facts when an API key is set. Topics and sentiment are derived from the facts, not from the
voice, so the extraction is stable. Aggregates per scenario and a baseline-versus-alternative comparison are
written to `runs/<id>/insights.json`.

## 7. Server and UI

`orgsim/server/app.py` is a FastAPI app serving the JSON API (every endpoint is listed in its docstring) and the
build-free UI under `ui/` (static HTML, CSS and ES modules; Chart.js, Cytoscape and marked from cdnjs). UI files are
served with no-cache headers and a version stamp so edits show on reload. Instances may add detailed views under
`instances/<id>/ui/`, embedded in Results.

## 8. Stack

Python 3.12 (`.venv` via uv), pandas, pyarrow, numpy, scipy, pydantic, FastAPI and uvicorn, httpx. Parquet for
traces, JSON for run summaries and documents, YAML for everything a person edits. No node toolchain.
