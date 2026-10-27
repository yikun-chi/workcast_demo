#!/usr/bin/env bash
# Push the working tree to the iMac SSD checkout (code only; data, runs and the venv stay where they are).
set -euo pipefail
cd "$(dirname "$0")/.."
ssh lab 'bash ~/bin/ensure_psychdynamics_mounted.sh >/dev/null 2>&1 || true'
rsync -a --delete --exclude .venv --exclude .git --exclude '/runs/' --exclude '/logs/' --exclude 'instances/*/data/' --exclude '/data/onet/' \
  --exclude __pycache__ --exclude .pytest_cache ./ lab:/Volumes/PsychDynamicsData/workcast_demo/
echo "synced to lab:/Volumes/PsychDynamicsData/workcast_demo"
