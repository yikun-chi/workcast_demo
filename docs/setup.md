# Setup and reproduction

Use the [quickstart](../README.md) for the shortest route to a running application.
This is the detailed operations reference. Architecture and planner design live in
[architecture](architecture.md) and [task planners](task-planners.md).

## Installation

From the repository root, with Python 3.12 and uv installed:

```bash
uv sync --locked --extra dev --python 3.12
uv run orgsim instances
uv run --locked --extra dev pytest -m 'not data' -q
```

`uv.lock` pins dependencies. Commands in this guide run from the repository root.
Keep the editable checkout: a standalone installation
of the Python wheel does not include the instance definitions or web UI. No Node
installation or model API key is required for the default rule policies and
template interviews. No credential file is needed for the standard demo.

LangGraph is an optional task-planner adapter. To install and exercise it, use the
[task-planner guide](task-planners.md#run-the-example). The eight instances and the rule
planner work without it. With the extra installed, use `.venv/bin/python` or
`uv run --extra langgraph` to retain it; a plain `uv sync` selects only base dependencies.

## Credential configuration

The [quickstart key table](../README.md#api-keys) lists which operations require a
credential. Set environment variables in the shell that launches `orgsim` or the
downloader; this application has no automatic `.env` loading.

For OpenRouter retrieval, either export `OPENROUTER_API_KEY` or save only the key
text in `~/.secrets/openrouter.key` outside the checkout. The environment variable
takes precedence. Restrict the key file to your user (`chmod 600 ~/.secrets/openrouter.key`).
This key is for data retrieval; evaluating data already on disk does not require it.

Hosted seat policies are optional and configured in
`instances/<id>/policies/seats.yaml`: `adapter: llm` reads `ANTHROPIC_API_KEY` and
`adapter: openai` reads `OPENAI_API_KEY`. Choose a model available to your account.
The OpenAI adapter also accepts a response `cache`, `max_usd` and `usd_per_mtok`
configuration; see [seat policies](architecture.md#2-kernel-and-policies).
Default instance policies use rules. Setting a key alone does not enable a hosted
seat. Missing credentials or failed calls can fall back to rules; inspect recorded
fallbacks before describing a run as model-driven.

Optional model-written interviews use `orgsim insights <id> --model <model-id>`
and `ANTHROPIC_API_KEY`. The default uses templates. Local seats use `adapter: local`,
`model` and a `base_url` pointing to a chat-completions endpoint; they read
`LOCAL_MODEL_API_KEY` or send the placeholder `local` for an unauthenticated server.
Give the model server a different port from the UI server.

## Data acquisition

```bash
uv run python scripts/download_data.py
```

The downloader uses the URLs and checksums in the committed manifests:

| Source | Destination | Preparation |
|---|---|---|
| O*NET 31.0 | `data/onet/` | Verify the archive and extract the listed tables |
| Trip.com replication deposit | `instances/trip/data/raw/6X4ZZL/` | Download and verify original Stata tables |
| BPI Challenge 2019 | `instances/bpi19/data/raw/` | Verify the conference mirror and decompressed XES; parse into normalized Parquet |
| Ctrip call-centre experiment (`ctrip`) | `instances/ctrip/data/raw/` | Verify the authors' replication ZIP; ingest extracts and normalizes it |
| Federal workforce (`fedwork`) | `instances/fedwork/data/raw/opm/` | Verify pinned monthly OPM Parquet files |
| Business AI adoption (`btos_ai`) | `instances/btos_ai/data/raw/` | Verify Census workbooks and question wording |
| AI task mix (`aei_tasks`) | `instances/aei_tasks/data/raw/` | Verify Economic Index files from a pinned Hugging Face revision; also needs O*NET |
| Stack Overflow (`so_chatgpt`) | `instances/so_chatgpt/data/raw/weekly/` | Use the original snapshot if available, or explicitly retrieve new API counts |
| AI demand (`openrouter`) | `instances/openrouter/data/raw/` | Use the original snapshot if available, or retrieve with an OpenRouter API key |

The BPI download expands to approximately 729 MB before parsed tables and run traces.
Allow several GB for the complete workflow. Downloads can be selected individually:

```bash
uv run python scripts/download_data.py onet
uv run python scripts/download_data.py trip
uv run python scripts/download_data.py bpi19
uv run python scripts/download_data.py --verify-only
```

Existing input files must match the recorded checksum. If a source is unavailable,
the downloader fails with the URL/error instead of substituting another dataset.
The original Trip.com comparison uses cited aggregate findings from the older Ctrip
study; the separate `ctrip` instance requires that study's replication ZIP. Raw Trip.com post-change outcomes
are available to the scoring code, but are not calibration inputs.

The default command retains the original O*NET, Trip.com and procurement downloads.
Use `public` for all pinned public inputs, or an instance ID for one source:

```bash
uv run python scripts/download_data.py public
uv run python scripts/download_data.py ctrip --verify-only
uv run python scripts/download_data.py so_chatgpt --refresh
uv run python scripts/download_data.py openrouter --refresh
```

API snapshots are not immutable archives. `--refresh` writes
`instances/<id>/data/sources.local.json`, preserving the committed
`manifests/sources.json`. Verification without `--refresh` checks the published
snapshot; `--refresh --verify-only` checks the local retrieval. Incomplete retrievals
fail verification and can be resumed. Anonymous Stack Exchange quotas may require
another day. A fresh snapshot can change results and must be re-evaluated.
OpenRouter reads `OPENROUTER_API_KEY` or `~/.secrets/openrouter.key`.

The repository includes manifests, not the original API snapshot files. Without
`--refresh`, these two sources verify files already on disk; they do not download
an immutable archive. Access to the original snapshots is tracked in
[issue #9](https://github.com/yikun-chi/workcast_demo/issues/9). A fresh retrieval
is the available alternative when the original files cannot be obtained.

For each additional instance, run `uv run orgsim demo <id>` after acquiring its
inputs. Individual steps are `uv run orgsim ingest <id>`, `uv run orgsim evaluate <id>`,
`uv run orgsim insights <id>`, and `uv run python instances/<id>/reports/build_report.py`.
The shared Results page uses local evaluations; a committed report is evidence from
the author's run and does not mean the data is installed here. `so_survey` is a
feasibility investigation, not a runnable instance. See the [board guide](../board/README.md)
for the separate ensemble/publisher and its original deployment helpers; data
download and evaluation do not deploy it.

## Reproduce the application

```bash
uv run orgsim demo trip
uv run orgsim demo bpi19
uv run orgsim serve --port 8000
```

Open `http://127.0.0.1:8000`. The browser needs internet access for the pinned cdnjs
libraries. The full demo takes tens of minutes, depending on available CPU and
storage. A Trip.com-only run uses `orgsim demo trip` after downloading O*NET and Trip.com.
Procurement uses `orgsim demo bpi19` after downloading O*NET and BPI.

`demo` normalizes the data, fits the configured pre-change procurement model, runs
the scenarios, evaluates them, and builds interviews and reports. It also refreshes
the validation document when evaluations for both instances exist. Individual steps:

```bash
uv run orgsim validate trip
uv run orgsim validate bpi19
uv run orgsim ingest trip
uv run orgsim ingest bpi19
uv run orgsim evaluate trip
uv run orgsim evaluate bpi19
uv run orgsim insights trip
uv run orgsim insights bpi19
uv run python instances/trip/reports/build_report.py
uv run python instances/bpi19/reports/build_report.py
uv run python scripts/build_validation_docs.py
```

`evaluate` runs the ensembles specified by each evaluation protocol, including
matched alternative scenarios. `orgsim run <id> --scenario <name> --seed 1` is a
single exploratory run; it does not replace the evaluated cohort displayed in Results.
Before-period observations are never simulated. Re-ingesting BPI refits
`instances/bpi19/calibration/process.json`; this file is intentionally included in
source control so its identity can be compared with the saved evaluation.

Generated runtime files live in `runs/` and `instances/*/data/` and are ignored by
Git. Current `reports/report.json` snapshots and the instance validation pages are included
as readable results; regenerate them after a new evaluation. UI fixtures under
`ui/dev/fixtures/` exercise development views and are not validation evidence.

## Explore AI assistance

Trip.com and procurement have an `ai_assistant` scenario in addition to their original
alternative. In Results, switch to the AI alternative under **Explore alternative
actions**. In Scenarios, adjust coverage, time saved before review, review effort,
correction rate, and correction effort. Save, then select **Compare with current
policy**. The comparison runs in the background and updates the AI Results panel.

From the command line, after the reference evaluations exist:

```bash
uv run orgsim explore trip --scenario ai_assistant
uv run orgsim explore bpi19 --scenario ai_assistant
```

These commands leave `evaluation.json` unchanged and write matched results to
`runs/<id>/explorations.json`. Trip.com uses the scenario's seeds with a newly run
reference cohort; procurement uses the evaluation's cutoffs and seeds and can
reuse reference runs from a prior AI comparison only when model, input, and reference
fingerprints match. Otherwise it reruns the reference cohort. `demo` and `evaluate`
also build these comparisons.
The command refreshes interviews, the instance report, and validation documentation.

Saved comparisons are tied to their assumptions, reference evaluation, model code,
calibration, and input tables. Editing these marks the comparison stale; its numbers
are hidden until it is rerun. A comparison can take several minutes. Progress and
failures are recorded in `exploration_status.json`, with server-launched logs in
`exploration.log` under the instance's run directory.

For the modeling boundaries and research context, see
[AI assistance](architecture.md#ai-assistance-as-an-exploratory-intervention).

## Deployment

The supported serving command is:

```bash
uv run orgsim serve --host 127.0.0.1 --port 8000
```

This starts the local development application. Editing and run endpoints have no
authentication. Keep the default loopback host. The UI currently fetches `/api/`
responses from Python; uploading `ui/` alone does not produce a working public site.

A public, read-only static export and a site-deployment workflow have not been
implemented. The existing [GitHub Actions workflow](../.github/workflows/tests.yml)
runs tests only. The development fixtures are test inputs, not saved instance results.

To publish the intended static demo, the remaining work is to export curated saved
results, make the shared UI read those files with run/edit actions disabled, and
add a build/deploy workflow for the chosen host and domain. Keep one source UI;
the static bundle should be generated output. Decide explicitly which result data
is public before exporting it. Local `runs/` and datasets are ignored by Git, so
rerunning an analysis locally does not by itself update a website: an export must
be committed or generated by the deployment workflow.

## Verification

The data-dependent tests use inputs and saved evaluations across the registered
instances, including O*NET. Download and prepare the relevant instances before
running the full suite. To include the optional planner checks as well:

```bash
uv sync --locked --extra dev --extra langgraph
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/check_bpi19_results.py
.venv/bin/python scripts/download_data.py public --verify-only
.venv/bin/python scripts/download_data.py openrouter --refresh --verify-only
.venv/bin/python scripts/download_data.py so_chatgpt --refresh --verify-only
```

The `data` pytest marker identifies checks that require local inputs or saved
evaluations. `pytest -m 'not data'` runs the portable checks; the full command above
does not silently skip missing datasets. Without the LangGraph extra, its checks
are skipped. GitHub Actions tests the portable suite with and without that extra.
For original API snapshots, omit `--refresh` when verifying; the commands above
verify explicitly refreshed local snapshots.

With the server running, visit both pages and confirm `DONE errors=0`:

- `http://127.0.0.1:8000/ui/dev/smoke.html?instance=trip`
- `http://127.0.0.1:8000/ui/dev/smoke.html?instance=bpi19`

The harness opens temporary iframes and can take a few minutes. Alternatively, use
a Chromium-compatible browser executable on your machine:

```bash
chromium --headless --disable-gpu --window-size=1400,1000 \
  --virtual-time-budget=120000 --dump-dom \
  'http://127.0.0.1:8000/ui/dev/smoke.html?instance=trip'
```

Repeat for `bpi19` and inspect each Results page visually, including the combined
actual-outcome/prediction table and the alternative scenario section. Restart the
server after changing Python code; `orgsim serve --reload` can do this during development.

## Repository maintenance

Use the current source checkout as the repository root. It is the single
working copy of the platform; no export or duplicate application folder is needed.

`.gitignore` excludes credentials, machine settings, virtual environments, caches,
downloaded datasets, run outputs, and local reading PDFs. Source code, documentation,
manifests, calibration files, and current report snapshots belong in Git.

The repository is [yikun-chi/workcast_demo](https://github.com/yikun-chi/workcast_demo).
Keep normal Git operations in this checkout; a separate `dist/` export is not part
of the workflow. Inspect changes before committing and pushing:

```bash
git status --short
git diff --check
git diff --stat
```

After staging the intended files, inspect `git diff --cached` and commit through
Git or GitHub Desktop. Ignore rules apply to Git;
manually dragging the entire directory into a web upload would also include local
files. Reference PDFs stay local; the bibliography and source manifests stay in
Git. No code license is added automatically.

Frozen protocols and sealed source snapshots preserve research provenance. Update
generated documents through their builders and use the
[documentation index](README.md) to find the current guide for each workflow.
