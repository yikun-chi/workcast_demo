"""Design choices for a service-world instance, on its development cutoffs only.

Runs the simulation (central path) and the classical comparators at every dev cutoff for each named variant of
calibration/service.yaml and prints the errors averaged over the dev cutoffs. Refuses any cutoff that is not a dev
cutoff, so the held-out cutoffs are never looked at while choosing. Results go to runs/<id>/dev/<variant>.json.

    uv run python scripts/service_dev.py cfpb_complaints --variants instances/cfpb_complaints/calibration/dev_variants.yaml
"""
from __future__ import annotations

import argparse
import copy
import json
import time

import yaml

from orgsim.instances import get_instance
from orgsim.worlds import service as sv


def merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--variants", required=True, help="YAML: {variant name: overrides of calibration/service.yaml}")
    ap.add_argument("--only", nargs="*", help="run only these variant names")
    a = ap.parse_args()
    ctx = get_instance(a.instance)
    proto = ctx.yaml("evaluation/protocol.yaml")
    base_cfg = ctx.yaml("calibration/service.yaml")
    dev = [str(c) for c in proto["dev_cutoffs"]]
    cutoffs = [str(c) for c in proto["cutoffs"]]
    assert dev == cutoffs[:len(dev)] and len(dev) <= -(-len(cutoffs) // 4), "dev cutoffs must be the earliest quarter of the cutoffs"
    variants = yaml.safe_load(open(a.variants)) or {}
    d = sv.load_data(ctx)
    cache: dict = {}
    out_dir = ctx.runs_dir / "dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, over in variants.items():
        if a.only and name not in a.only:
            continue
        cfg = merge(base_cfg, over)
        t = time.time()
        windows = [sv.forecast_cutoff(ctx, d, c, cfg, proto, [1], write_runs=False, comp_cache=cache) for c in dev]
        keys = sorted({k for w in windows for k in w["scores"]})
        summ = sv.summarise(windows, keys, list(sv.COMPARATOR_LABELS))
        bh = {hb: {k: sv._mean([w["by_horizon"][hb][k] for w in windows]) for k in ["simulation", *sv.COMPARATOR_LABELS]} for hb in windows[0]["by_horizon"]}
        (out_dir / f"{name}.json").write_text(json.dumps({"variant": name, "overrides": over, "summary": summ, "by_horizon": bh,
                                                           "windows": [{k: w[k] for k in ("cutoff", "scores", "calibration", "by_horizon")} for w in windows]},
                                                          indent=1, default=sv._json_default))
        print(f"\n=== {name} ({time.time() - t:.0f}s) overrides={json.dumps(over)}")
        for k, s in summ.items():
            e = s["errors"]
            print(f"  {k:28s} sim {e['simulation']:.4f} | " + " ".join(f"{c} {e[c]:.4f}" for c in sv.COMPARATOR_LABELS)
                  + f" | best {s['best_baseline']} red {s['error_reduction_pct']:.1f}%")
        print("  by horizon (volume WAPE): " + "; ".join(f"{hb}: sim {v['simulation']:.4f} ets {v['ets']:.4f} recent {v['recent_average']:.4f}" for hb, v in bh.items()))
        print("  chosen specs (last dev cutoff):", json.dumps(windows[-1]["calibration"]["spec_by_tier"]), "| kappa", windows[-1]["calibration"]["kappa"],
              "| eta", windows[-1]["calibration"]["eta"], flush=True)


if __name__ == "__main__":
    main()
