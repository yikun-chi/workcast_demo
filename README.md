# WORKCAST quickstart

Run the simulation application from this source checkout. This guide covers setup
and operation; [docs/](docs/README.md) contains the project overview and technical guides.
Agents should read [agent.md](agent.md) before making changes.

Public read-only demo: **[workcast.yikun.io](https://workcast.yikun.io)**.

## Python and uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from
the repository root:

```bash
uv sync --locked --extra dev --python 3.12
uv run orgsim instances
```

Use Python 3.12 and the committed `uv.lock`. Keep the editable source checkout:
`instances/`, `ui/` and `data/` are loaded beside the Python package. A standalone
wheel is insufficient. No Node installation or frontend build is required.

## API keys

| Operation | Required credential |
|---|---|
| Default simulations, saved-data evaluation and template interviews | None |
| Bundled rule and LangGraph task-planner examples | None |
| Fresh OpenRouter dataset retrieval | `OPENROUTER_API_KEY`, or a key in `~/.secrets/openrouter.key` |
| Optional Anthropic seat policies or model-written interviews | `ANTHROPIC_API_KEY` |
| Optional OpenAI seat policy | `OPENAI_API_KEY` |
| Optional local model server | `LOCAL_MODEL_API_KEY` if the server requires it; otherwise the adapter sends `local` |

Only configure the services you use. Export keys in the shell running the command;
the application does not automatically load a `.env` file. Keep credentials out of
Git. See [credential configuration](docs/setup.md#credential-configuration) for
optional policy settings and the OpenRouter key-file location.

## Download data

To restore the saved datasets **and cleaned simulation runs** from the GitHub release:

```bash
uv run python scripts/release_snapshot.py download --tag snapshot-2026-11-03
uv run python scripts/release_snapshot.py restore --tag snapshot-2026-11-03
uv run orgsim serve --port 8000
```

Restoration verifies archive/file checksums and refuses to overwrite different local
files. It needs no OpenRouter or model API key. See [release snapshots](docs/setup.md#release-snapshots)
for data-only/run-only downloads and the snapshot's known limitations.

To acquire inputs from their original sources and recompute instead:

For the original Trip.com and procurement examples:

```bash
uv run python scripts/download_data.py
```

This fetches O*NET, Trip.com and BPI Challenge 2019, verifies pinned checksums, and
parses the BPI log. For a smaller Trip.com-only setup, use `onet` and `trip` as
separate source arguments instead. For the additional datasets:

```bash
uv run python scripts/download_data.py public                  # all pinned public inputs
uv run python scripts/download_data.py so_chatgpt --refresh    # new API snapshot; no key
uv run python scripts/download_data.py openrouter --refresh    # requires OpenRouter key
```

Allow several GB of disk space. Inputs and runs remain local and are ignored by
Git. A fresh API retrieval can differ from the published snapshot; re-evaluate it.
See [data acquisition](docs/setup.md#data-acquisition) for per-instance paths,
original snapshot access, quotas and verification options.

## Run and open the application

```bash
uv run orgsim demo trip
uv run orgsim demo bpi19
uv run orgsim serve --port 8000
```

Open **http://127.0.0.1:8000**. Each `demo` command prepares data, runs the simulation
and builds evaluation, interviews and reports. Use `orgsim demo <instance-id>` for
another installed dataset. Full evaluations can take tens of minutes. The browser
needs internet access for pinned libraries loaded from cdnjs.

After results exist, subsequent visits only require `orgsim serve`. Committed
reports do not replace the local data and run artifacts needed by the interactive
UI. See [reproduction](docs/setup.md#reproduce-the-application) for individual steps
and [AI exploration](docs/setup.md#explore-ai-assistance) for refreshing alternatives.

## Optional dependencies

The task-planner example can also run with the LangGraph extra:

```bash
uv sync --locked --extra dev --extra langgraph --python 3.12
uv run --extra langgraph orgsim workflow --planner langgraph
```

A plain `uv sync` removes unselected extras. Use `.venv/bin/python` with the current
environment, or repeat the relevant `--extra` options. See the
[task-planner guide](docs/task-planners.md) for example commands and replay.

## Deployment

The public site uses GitHub Pages and the same UI with editing/reruns disabled.
GitHub Actions rebuilds it when UI or committed result snapshots change on `main`.
Refresh results and preview the static build with:

```bash
uv run python scripts/export_site.py snapshot   # requires prepared local results
uv run python scripts/export_site.py build
python3 -m http.server 9000 --directory build/site
```

Open `http://localhost:9000`. Commit the refreshed `public-data/` files to publish
new analysis. The site build itself requires only Python's standard library and
the committed snapshots. See [deployment](docs/setup.md#deployment) for the workflow.
The interactive `orgsim serve` remains a local application without authentication;
keep its default loopback address.

## Verify the installation

Without downloaded data:

```bash
uv run --locked --extra dev pytest -m 'not data' -q
```

After preparing the datasets and evaluations required by the full suite:

```bash
uv run --locked --extra dev pytest -q
uv run python scripts/check_bpi19_results.py
```

For checks including the optional planner and browser UI, see
[verification](docs/setup.md#verification). Downloaded inputs retain their source
licenses; see [data attribution](docs/overview.md#data-and-licensing).
