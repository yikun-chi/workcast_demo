"""Verify the current procurement result's data boundary, paired runs and business comparisons."""
import json
import hashlib
import math
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from orgsim.instances import get_instance


def check():
    ctx = get_instance("bpi19")
    result = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    calibration = json.loads((ctx.calibration_dir / "process.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert result["calibration_sha256"] == calibration["sha256"], "Evaluation uses a different calibration"
    payload = {k: v for k, v in calibration.items() if k != "sha256"}
    assert hashlib.sha256(json.dumps(payload, indent=1).encode()).hexdigest() == calibration["sha256"], "Calibration contents have changed"
    change = pd.Timestamp(proto["change_date"])
    assert pd.Timestamp(calibration["fitted_on"]["events_until"]) < change
    assert result["periods"]["before"]["runs"] == 0, "Before must contain observations only"
    assert all(pd.Timestamp(c) + pd.Timedelta(days=proto["horizon_days"]) <= change for c in proto["before_cutoffs"])
    expected = {(c, s) for c in proto["cutoffs"] for s in proto["seeds"]}
    actual = {(r["t0"], r["seed"]) for r in result["per_run"]}
    assert actual == expected and len(result["per_run"]) == len(expected)
    for scenario, ids in result["run_ids"].items():
        assert len(ids) == len(set(ids)) == len(expected), "Scenarios must use matching runs"
        pairs = set()
        for rid in ids:
            directory = ctx.runs_dir / scenario / rid
            config = json.loads((directory / "config.json").read_text())
            assert (directory / "summary.json").exists() and (directory / "trace.parquet").exists()
            pairs.add((config["scenario"]["world"]["t0"], config["seed"]))
        assert pairs == expected, f"Unmatched periods or seeds: {scenario}"
    metric_keys = {"completion_14d": "completion_rate", "median_cycle_hours": "median_cycle_h",
                   "exception_rate": "exception_rate", "handoffs_per_case": "handoffs_per_active_case", "events_per_week": "weekly_events"}
    by_cutoff = defaultdict(list)
    for row in result["per_run"]:
        by_cutoff[row["t0"]].append(row)
    mean = lambda values: sum(values) / len(values)
    value = lambda x: mean(x) if isinstance(x, list) else x
    for score in result["business_validation"]:
        key = metric_keys[score["id"]]
        for window in score["windows"]:
            rows = by_cutoff[window["cutoff"]]
            assert math.isclose(window["simulated"], mean([value(r["sim"][key]) for r in rows]))
            assert all(math.isclose(window["actual"], value(r["act"][key])) for r in rows)
        mae = mean([abs(w["simulated"] - w["actual"]) for w in score["windows"]])
        assert math.isclose(mae, score["simulation_mae"])
        for name, error in score["baseline_mae"].items():
            assert math.isclose(error, mean([abs(w["baselines"][name] - w["actual"]) for w in score["windows"]]))
        best = min(score["baseline_mae"].values())
        assert math.isclose(score["baseline_mae"][score["best_baseline"]], best)
        assert score["beats_best_baseline"] == (mae < best)
        assert math.isclose(score["error_reduction_pct"], 100 * (1 - mae / best))
        print(f"{score['id']}: verified error reduction {score['error_reduction_pct']:.1f}%")
    print("Verified pre-policy fitting, observed Before, matching scenarios, and all business comparisons.")


if __name__ == "__main__":
    check()
