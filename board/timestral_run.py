"""Timestral base forecasts for Run 4 of docs/plans/astra_forecast_protocol.md.

Runs in its own venv (timestral pins its own torch), so it reads the histories board/combo4.py --stage export wrote and
writes weekly log-scale median and 10% / 90% quantiles for 8 weeks per app:

    .tsvenv/bin/python board/timestral_run.py --out /Volumes/PsychDynamicsData/workcast_board/astra
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from timestral import TimestralForecaster

REPO = "mistralai/Timestral-209M"
H = 8


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src, dst = Path(a.out) / "timestral_in", Path(a.out) / "timestral_out"
    dst.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)
    model = TimestralForecaster.from_pretrained(REPO, device="cpu")
    for p in sorted(src.glob("*.npz")):
        if (dst / p.name).exists():
            continue
        z = np.load(p)
        with torch.no_grad():
            f = model.forecast(z["logx"].astype(np.float32), prediction_length=H)
        flat = lambda t: np.asarray(t.cpu() if hasattr(t, "cpu") else t, dtype=float).reshape(len(z["ids"]), H)
        np.savez(dst / p.name, ids=z["ids"], median=flat(f.median), q10=flat(f.quantile(0.1)), q90=flat(f.quantile(0.9)), repo=REPO)
        print(p.stem, z["logx"].shape, "median week-1 range", flat(f.median)[:, 0].min().round(2), flat(f.median)[:, 0].max().round(2), flush=True)


if __name__ == "__main__":
    main()
