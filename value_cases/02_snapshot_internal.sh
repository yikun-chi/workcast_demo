#!/usr/bin/env bash
# Copy the repository results the value cases cite into sources/internal/ and hash them.
# The OpenRouter evaluation is a git-ignored run output on the iMac SSD checkout, so it is copied from there.
# Writes sources/internal/manifest.json (file, copied_from, last commit of the original, bytes, sha256).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p sources/internal
scp -q lab:/Volumes/PsychDynamicsData/workcast_demo/runs/openrouter/evaluation.json sources/internal/openrouter_evaluation.json
# study teams' evaluations (git-ignored run outputs in their iMac checkouts)
scp -q lab:/Volumes/PsychDynamicsData/workcast_workforce/runs/ctrip/evaluation.json sources/internal/ctrip_evaluation.json
scp -q lab:/Volumes/PsychDynamicsData/workcast_adoption/runs/btos_ai/evaluation.json sources/internal/btos_ai_evaluation.json
scp -q lab:/Volumes/PsychDynamicsData/workcast_adoption/runs/so_chatgpt/evaluation.json sources/internal/so_chatgpt_evaluation.json
cp ../docs/validation.md sources/internal/validation_trip_bpi19.md
cp ../instances/trip/instance.yaml sources/internal/trip_instance.yaml
cp ../instances/bpi19/scenarios/no_expansion.yaml sources/internal/bpi19_no_expansion.yaml
python3 - <<'PY'
import hashlib, json, subprocess, datetime
from pathlib import Path
d = Path("sources/internal")
origin = {"openrouter_evaluation.json": ("runs/openrouter/evaluation.json on the iMac checkout (git-ignored run output)", None),
          "ctrip_evaluation.json": ("runs/ctrip/evaluation.json, iMac /Volumes/PsychDynamicsData/workcast_workforce (branch workforce-retrodiction)", None),
          "btos_ai_evaluation.json": ("runs/btos_ai/evaluation.json, iMac /Volumes/PsychDynamicsData/workcast_adoption (branch adoption-retrodiction)", None),
          "so_chatgpt_evaluation.json": ("runs/so_chatgpt/evaluation.json, iMac /Volumes/PsychDynamicsData/workcast_adoption (branch adoption-retrodiction)", None),
          "validation_trip_bpi19.md": ("docs/validation.md", "docs/validation.md"),
          "trip_instance.yaml": ("instances/trip/instance.yaml", "instances/trip/instance.yaml"),
          "bpi19_no_expansion.yaml": ("instances/bpi19/scenarios/no_expansion.yaml", "instances/bpi19/scenarios/no_expansion.yaml")}
man = []
for f in sorted(d.iterdir()):
    if f.name == "manifest.json":
        continue
    src, tracked = origin[f.name]
    commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", tracked], capture_output=True, text=True, cwd="..").stdout.strip() if tracked else None
    man.append({"file": f.name, "copied_from": src, "last_commit_of_original": commit,
                "copied_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "bytes": f.stat().st_size, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
(d / "manifest.json").write_text(json.dumps(man, indent=1))
for m in man:
    print(m["file"], m["sha256"][:12], m["last_commit_of_original"])
PY
