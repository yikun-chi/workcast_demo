"""Build reports/report.json from runs/btos_ai/evaluation.json (orgsim.worlds.adoption.build_report). Every number is
read from the evaluation; nothing is typed in by hand.

    .venv/bin/python instances/btos_ai/reports/build_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.worlds.adoption import build_report  # noqa: E402

if __name__ == "__main__":
    build_report(get_instance("btos_ai"))
    print("wrote instances/btos_ai/reports/report.json")
