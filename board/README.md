# Prediction board

This directory contains a separate AI-demand ensemble and publishing workflow.
The shared simulation application runs with `orgsim serve` and does not need these
scripts. Installing the application, downloading data or evaluating an instance
does not deploy or schedule the board.

## Code and evidence

- `forecast_openrouter.py` creates prediction records using the configured ensemble.
- `score_openrouter.py` scores records on available actual outcomes and common cutoffs.
- `chart_data.py` and `build_site.py` prepare charts and a static page from saved inputs.
- `astra_backtest.py`, `combo*.py`, `fair_inputs.py` and `timestral_run.py` are research tools.
- `results/` contains recorded research outputs cited by the
  [board protocol](../docs/plans/astra_forecast_protocol.md). Required component
  responses and caches are not all included in Git.

The published combination and retrospective charts have different method identities;
this is tracked in [issue #6](https://github.com/yikun-chi/workcast_demo/issues/6).
Original snapshot and cache availability is tracked in
[issue #9](https://github.com/yikun-chi/workcast_demo/issues/9). The OpenRouter
instance also has documented [input-boundary limitations](../docs/validation_openrouter.md).
Keep board ensembles, individual simulation results and prospective records distinct
when describing accuracy.

## Deployment helpers

`run_board.sh`, `publish_from_laptop.sh`, `install_laptop_job.sh`, the launchd plist
and `scripts/sync_imac.sh` describe the original author's Mac/SSH/Cloudflare setup.
They contain host, volume and project names specific to that installation. They
are not portable setup commands and are not invoked by the main application or CI.
The sync helper uses `rsync --delete`; the installer registers a recurring job;
the publisher uploads a site. Configure and review those destinations before any
intentional deployment. No board deployment is required for this repository's demo.

Some research and prediction scripts can call paid models. Their historical run
budgets in the protocol are provenance, not authorization for new calls. Local
credentials and component caches stay outside the committed source.
