# Setup and reproduction

## Installation

From the repository root, with Python 3.12 and uv installed:

```bash
uv sync --locked --extra dev --python 3.12
uv run orgsim instances
uv run --locked --extra dev pytest -m 'not data' -q
```

`uv.lock` pins dependencies. Keep the editable checkout: a standalone installation
of the Python wheel does not include the instance definitions or web UI. No Node
installation or model API key is required for the default rule policies and
template interviews. Optional hosted policies read `ANTHROPIC_API_KEY` from the
environment; local model policies use `LOCAL_MODEL_API_KEY`. No credential file is
needed for the standard demo. The server is a local development application; its
editing and run endpoints have no authentication. Keep the default loopback host.

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
The older Ctrip study is used through cited aggregate findings; its optional
replication ZIP is not required or downloaded. Raw Trip.com post-change outcomes
are available to the scoring code, but are not calibration inputs.

## Reproduce the application

```bash
uv run orgsim demo
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
Git. Current `reports/report.json` snapshots and `docs/validation.md` are included
as readable results; regenerate them after a new evaluation. UI fixtures under
`ui/dev/fixtures/` exercise development views and are not validation evidence.

## Verification

With both datasets normalized and both evaluations present:

```bash
uv run --extra dev pytest -q
uv run python scripts/check_bpi19_results.py
uv run python scripts/download_data.py --verify-only
```

The `data` pytest marker identifies checks that require local inputs or saved
evaluations. `pytest -m 'not data'` runs the portable checks; the full command above
does not silently skip missing datasets. GitHub Actions runs the portable subset.

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

## Upload this repository to GitHub

Use this `org_simulation/` directory as the repository root. It is the single
working copy of the platform; no export or duplicate application folder is needed.

`.gitignore` excludes credentials, machine settings, virtual environments, caches,
downloaded datasets, run outputs, and local reading PDFs. Source code, documentation,
manifests, calibration files, and current report snapshots belong in Git.

From this directory, stage and inspect the changes before committing and pushing:

```bash
git add --all
git diff --cached --stat
git status --short
```

Use Git or GitHub Desktop to publish the repository. Ignore rules apply to Git;
manually dragging the entire directory into a web upload would also include local
files. Reference PDFs have been removed from Git's index while their local copies
remain available. Existing commits may still contain those PDFs; history has not
been rewritten. No code license is added automatically.
