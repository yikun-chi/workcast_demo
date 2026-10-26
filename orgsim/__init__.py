"""orgsim: organization simulation platform core.

Dataset-agnostic. Worlds (instances) configure it; see docs/architecture.md.
"""
from pathlib import Path

__version__ = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTANCES_DIR = REPO_ROOT / "instances"
DATA_DIR = REPO_ROOT / "data"
RUNS_DIR = REPO_ROOT / "runs"
UI_DIR = REPO_ROOT / "ui"
