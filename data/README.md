# Shared reference data

Shared reference data is downloaded into this directory and excluded from Git.
The committed [O*NET manifest](manifests/onet_31_0.json) records the source URL,
checksum, file list, and attribution.

From the repository root: `uv run python scripts/download_data.py onet`.
Instance datasets live under `instances/<id>/data/`. See
[setup and reproduction](../docs/setup.md) for all data and run commands.
