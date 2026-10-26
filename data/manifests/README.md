# Manifests for shared reference data

One JSON per shared source: URL, retrieval date, hash, size, license, and file list.
`onet_31_0.json` is consumed by `scripts/download_data.py`; its archive checksum and
extracted files are verified before use. Instance-specific sources are recorded in
`instances/<id>/manifests/`.
