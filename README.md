# WORKCAST simulation platform

WORKCAST models how people and work processes respond to organizational changes.
Each instance follows the same sequence: **observed before → change → actual outcome,
other prediction, and simulation prediction → alternative behavior**. Before-period
data supplies context and calibration; only after-change predictions are scored.
Interviews describe simulated agents, not statements from real employees.

Each instance includes two alternatives: its original policy alternative and an AI
assistant. In Results, use **Explore alternative actions** to switch between them.
AI assumptions are editable in Scenarios; **Compare with current policy** runs a
matched comparison. The AI cases estimate workload and operational effects under
stated assumptions; they have no observed AI outcome in these datasets.

| Instance | Company and decision | Headline (computed, see `docs/validation.md`) |
|---|---|---|
| `trip` | Trip.com: two work-from-home days a week? | Attrition effect -2.39 pp predicted vs -2.40 pp actual; retrospective evaluation; neither group's post-change outcomes used for calibration |
| `bpi19` | Purchase-to-pay: predict operations after the workforce expansion | Lower error across prediction windows than the best non-simulation comparator on 3 of 5 business outcomes; details in [validation](docs/validation.md) |

Trip.com is a retrospective evaluation: neither group's post-change outcomes enter
the current calibration, but the inherited prior history includes outcome-based
selection. Procurement predictions use actual incoming orders and the operating
state at each prediction date. These are conditional predictions, not an advance
prediction of all demand or proof that staffing alone caused the observed changes.

## Set up a source checkout

Use Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/)
(0.13.1 was used to generate the lockfile). Run from the repository root:

```bash
uv sync --locked --extra dev --python 3.12
uv run --locked --extra dev pytest -m 'not data' -q
uv run orgsim instances
```

The editable source checkout is required: the application loads `instances/`, `ui/`
and `data/` beside the Python package. There is no Node build step. The default
simulation and interview modes need no API key. The browser loads pinned Chart.js,
Cytoscape and marked libraries from cdnjs, so the full UI requires internet access.

## Download data and run

```bash
uv run python scripts/download_data.py      # fetch pinned inputs, verify hashes, parse BPI log
uv run orgsim demo                         # normalize, simulate, evaluate, build interviews and reports
uv run orgsim serve                        # http://127.0.0.1:8000
```

Allow several GB of disk space and tens of minutes for the full evaluation; runtime
depends on the machine. Downloads and runs stay local and are excluded from Git.
The downloader reuses verified inputs and never silently overwrites a corrupt file.
The source includes generated report snapshots and validation documentation; the
interactive results require local data and runs.

For a smaller first run, download `onet` and `trip` separately, then run `orgsim demo trip`.
See [setup and reproduction](docs/setup.md) for the full sequence, individual steps,
data verification, and browser checks.

## Verification

After both instances have run:

```bash
uv run --extra dev pytest -q
uv run python scripts/check_bpi19_results.py
```

GitHub Actions runs the tests that do not require downloaded data. The full dataset
checks and browser smoke tests are described in [setup](docs/setup.md#verification).

## Documentation

- [Setup and reproduction](docs/setup.md): installation, data, commands, verification, and GitHub upload.
- [Validation](docs/validation.md): data boundaries, comparison methods, results, and limitations.
- [Architecture](docs/architecture.md): simulation kernel, worlds, policies, ontology, and evaluation.
- [Contracts](docs/contracts.md): instance files, API responses, and UI data shapes.
- [UI guide](docs/ui.md): instance pages and the shared framing.
- [Foundations](docs/literature/foundations.md): design references and behavioral-prior sources.
- [Contributor guide](CLAUDE.md): rules and workflows for work on the repository.

## Data and licensing

Trip.com replication data, BPI Challenge 2019, and O*NET 31.0 are attributed in their
[Trip.com](instances/trip/manifests/sources.json),
[BPI](instances/bpi19/manifests/sources.json), and
[O*NET](data/manifests/onet_31_0.json) manifests, which record CC BY 4.0 terms.
Source downloads retain their original licenses. Reading PDFs stay local and are
excluded from Git. A code license has not been selected for this repository.
