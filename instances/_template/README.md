# Instance template

Create `instances/<id>/` using this checklist (see the [instance contract](../../docs/contracts.md#1-instance-folder)).
This folder contains documentation only; it is not a runnable scaffold.

- `instance.yaml`: `id`, `title`, `company`, `problem` (the business question), `situation`, `data_used`, `intro`, `world_type`
  (`workforce`, `process`, `market` or `adoption`), `world`, `clock`, `scenarios: {baseline, alternative, additional_alternatives?}`, `protocol_line`, `source`, `status`
- `manifests/sources.json`: every source file with URL, retrieval date, hash, size, license
- `ingest/run.py` with `main(ctx)`: raw -> `data/normalized/*` and `summary.json` (plus audit scripts under `ingest/audit/`)
- `ontology/bindings.yaml`: org units, locations, roles -> O*NET-SOC, activities -> DWA, systems, policies, latent states
- `policies/seats.yaml`: which supported seat adapter acts in each seat; see [policies](../../docs/architecture.md#2-kernel-and-policies)
- `calibration/`: parameters fitted on the training window only, or priors with a cited source per parameter
- `scenarios/baseline.yaml` and a primary alternative (with `short_title`); additional named alternatives go in `additional_alternatives`. The matched AI exploration currently supports workforce and process workloads. Unnamed files remain CLI-only.
- `evaluation/protocol.yaml`: what is scored, against what, with which baselines
- `reports/build_report.py`: builds `report.json` from the evaluation and run outputs
- `ui/` (optional): detailed views listed in `pages.json`, embedded in Results
- `data/` (git-ignored): `raw/` as downloaded, `normalized/` as produced by ingest

Then: `orgsim validate <id>`, `orgsim ingest <id>`, `orgsim run <id> --scenario baseline --seeds 1,2,3`, the same for
the alternative, `orgsim evaluate <id>`, `orgsim insights <id>`, `uv run python instances/<id>/reports/build_report.py`.

Use the existing instance closest to your world type as an example. Preserve the
shared before/change/outcomes/alternatives framing and document calibration cutoffs
and source availability. Task-planner framework adapters are a separate extension
point described in the [authored workflow guide](../../examples/README.md).
