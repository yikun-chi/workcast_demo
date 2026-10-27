"""Development check (not a reported result): deterministic median paths of several company-dynamics specifications
against carry-forward at every protocol cutoff, using only the functions the world uses.

  python instances/openrouter/ingest/audit/probe_specs.py
"""
import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

ctx = get_instance("openrouter"); d = M.load_data(ctx)
proto = ctx.yaml("evaluation/protocol.yaml"); par = ctx.yaml("calibration/market.yaml")
H, N = 8, 100
rows = []
for c in proto["cutoffs"]:
    t0 = pd.Timestamp(c)
    ids = M.top_apps(d, t0, N)
    hist = sorted(w for w in d.aw.week.unique() if t0 - 26 * M.WEEK <= w < t0)
    x, _ = M.app_matrix(d, hist, ids)
    y, cens = M.app_matrix(d, [t0 + i * M.WEEK for i in range(H)], ids)
    f = {"ylog": np.log(x), "y": y, "cens": cens, "cls": M.persistence_class(d, ids, t0), "fill": M.fill_level(d, t0)}
    dyn = M.fit_company_dynamics(d, t0, N, H, par["grid"], int(par["inner_cutoffs"]), 26)
    ta = y.sum(1)
    cf = np.repeat(x[:, -4:].mean(1)[:, None], H, 1).sum(1)
    no_surv = {cl: [1.0] * H for cl in M.PERSISTENCE}
    specs = {
        "carry_forward": cf,
        "cf+survival": M.point_paths(f, H, 4, 0.0, 0.5, 0.0, {"_all": 0.0}, dyn["survival"]).sum(1),
        "selected": M.point_paths(f, H, dyn["k_level"], 1.0, dyn["phi"], dyn["w"], dyn["mu"], dyn["survival"]).sum(1),
        "selected_no_surv": M.point_paths(f, H, dyn["k_level"], 1.0, dyn["phi"], dyn["w"], dyn["mu"], no_surv).sum(1),
    }
    r = {"cutoff": c, "spec": f'{dyn["k_level"]}|{dyn["drift_weight"]}|{dyn["phi"]}|{dyn["w"]}'}
    r.update({k: round(M.wape(v, ta), 1) for k, v in specs.items()})
    rows.append(r); print(r, flush=True)
df = pd.DataFrame(rows)
print(df.drop(columns=["cutoff", "spec"]).mean().round(1).to_dict())
