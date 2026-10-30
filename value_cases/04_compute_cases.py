"""Compute every number the value-case copy states from sealed/inputs.csv and assumptions.yaml.

Writes sealed/case_numbers.csv: id, value, display (exactly as printed), formula, inputs (ids the formula reads).
The copy renderer prints only `display` strings from this file, so every figure in the copy has a row here.

    python3 value_cases/04_compute_cases.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
WORDS = {4: "four", 5: "five", 6: "six", 9: "nine"}

inp = {r["id"]: float(r["value"]) for r in csv.DictReader((HERE / "sealed" / "inputs.csv").open())}
A = yaml.safe_load((HERE / "assumptions.yaml").read_text())
rows: list[dict] = []


def put(id_: str, value: float, display: str, formula: str, uses: list[str]) -> float:
    rows.append({"id": id_, "value": value, "display": display, "formula": formula, "inputs": " ".join(uses)})
    print(f"{id_:32s} {display:>14s}   {formula}")
    return value


def usd(x: float, step: int = 1000) -> str:
    """Dollars rounded to `step` for the copy ($2.4 million style above one million)."""
    if x >= 1e6:
        v = f"{x / 1e6:.1f}"
        return f"${v[:-2] if v.endswith('.0') else v} million"
    return f"${round(x / step) * step:,.0f}"


def pct(x: float, d: int = 0) -> str:
    return f"{x:.{d}f}%"


def accuracy(pred: float, actual: float) -> float:
    """Percent accuracy of a prediction: 100 x (1 - |pred - actual| / |actual|)."""
    return 100 * (1 - abs(pred - actual) / abs(actual))


def commitment_saving_per_million(d: float) -> float:
    """Saving per $1M of annual spend from committing capacity at discount d against the simulation's forecast of
    the leading apps' combined spend instead of the best standard forecast's (same rule as
    scripts/build_openrouter_validation.py: loss = (1 - d) x over-commitment + d x under-commitment)."""
    man = {m["file"]: m["sha256"] for m in json.loads((HERE / "sources/internal/manifest.json").read_text())}
    p = HERE / "sources/internal/openrouter_evaluation.json"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == man["openrouter_evaluation.json"]
    ev = json.loads(p.read_text())
    ts = next(b for b in ev["business_validation"] if b["id"] == "top_spend")
    total = sum(w["actual"] for w in ts["windows"])
    def loss(get):
        return sum((1 - d) * max(get(w) - w["actual"], 0) + d * max(w["actual"] - get(w), 0) for w in ts["windows"]) / total
    best = min((loss(lambda w, k=k: w["baselines"][k]) for k in ts["baseline_mae"]))
    return (best - loss(lambda w: w["simulated"])) * 1e6


def main() -> None:
    n = A["firm_employees"]
    put("firm_employees", n, f"{n:,}", "assumption", [])

    # ---- 1. pilot (Trip.com)
    put("c1_trip_employees", inp["trip_employees"], f"{inp['trip_employees']:,.0f}", "input", ["trip_employees"])
    put("c1_trial_months", inp["trip_trial_months"], WORDS[int(inp["trip_trial_months"])], "input", ["trip_trial_months"])
    put("c1_effect_sim", abs(inp["trip_attrition_effect_sim"]), f"{abs(inp['trip_attrition_effect_sim']):.2f}", "|input|", ["trip_attrition_effect_sim"])
    put("c1_effect_actual", abs(inp["trip_attrition_effect_actual"]), f"{abs(inp['trip_attrition_effect_actual']):.2f}", "|input|", ["trip_attrition_effect_actual"])
    a1 = put("c1_accuracy", accuracy(inp["trip_attrition_effect_sim"], inp["trip_attrition_effect_actual"]), "", "100 x (1 - |sim - actual| / |actual|)",
             ["trip_attrition_effect_sim", "trip_attrition_effect_actual"])
    rows[-1]["display"] = pct(a1, 1); print("   ->", rows[-1]["display"])
    er = 100 * (1 - abs(inp["trip_attrition_effect_sim"] - inp["trip_attrition_effect_actual"]) / abs(inp["trip_benchmark_effect"] - inp["trip_attrition_effect_actual"]))
    put("c1_error_reduction", er, pct(er), "100 x (1 - |sim - actual| / |benchmark - actual|)", ["trip_attrition_effect_sim", "trip_attrition_effect_actual", "trip_benchmark_effect"])
    ba = accuracy(inp["trip_benchmark_effect"], inp["trip_attrition_effect_actual"])
    put("c1_benchmark_accuracy", ba, pct(ba, 1), "accuracy of the earlier-study rule of thumb", ["trip_benchmark_effect", "trip_attrition_effect_actual"])
    mc, mo = A["pilot_decision_months_classical"], A["pilot_decision_months_ours"]
    put("c1_months_classical", mc, WORDS[mc], "assumption", [])
    put("c1_months_ours", mo, WORDS[mo], "assumption", [])
    put("c1_months_sooner", mc - mo, WORDS[mc - mo], "classical - ours", [])
    rep = inp["gallup_replacement_low"] * A["average_salary_usd"]
    put("c1_salary", A["average_salary_usd"], f"${A['average_salary_usd']:,}", "assumption", [])
    put("c1_replacement_cost", rep, f"${rep:,.0f}", "gallup_replacement_low x salary", ["gallup_replacement_low"])
    put("c1_replacement_low", inp["gallup_replacement_low"], "one-half", "input", ["gallup_replacement_low"])
    put("c1_replacement_high", inp["gallup_replacement_high"], "two times", "input", ["gallup_replacement_high"])
    dep = n * abs(inp["trip_attrition_effect_actual"]) / 100 * (mc - mo) / inp["trip_trial_months"]
    put("c1_departures_avoided", dep, f"{dep:.0f}", "firm x |actual effect| / 100 x months sooner / trial months", ["trip_attrition_effect_actual", "trip_trial_months"])
    put("c1_effect_used", abs(inp["trip_attrition_effect_actual"]), f"{abs(inp['trip_attrition_effect_actual']):.2f}", "|actual effect| per trial period", ["trip_attrition_effect_actual"])
    put("c1_value", dep * rep, usd(dep * rep), "departures avoided x replacement cost", ["trip_attrition_effect_actual", "gallup_replacement_low"])
    put("c1_value_exact", dep * rep, f"${dep * rep:,.0f}", "same, unrounded", [])

    # ---- 2. sizing a change (Ctrip performance effect)
    es, ea, el = inp["ctrip_perf_effect_sim"], inp["ctrip_perf_effect_actual"], inp["ctrip_perf_effect_literature"]
    put("c2_effect_sim", es, f"+{es:.2f}", "input", ["ctrip_perf_effect_sim"])
    put("c2_effect_actual", ea, f"+{ea:.2f}", "input", ["ctrip_perf_effect_actual"])
    put("c2_effect_literature", el, f"+{el:.2f}", "input (best comparator)", ["ctrip_perf_effect_literature", "ctrip_perf_best_comparator_is_literature"])
    r2 = 100 * (1 - abs(es - ea) / abs(el - ea))
    put("c2_error_reduction", r2, pct(r2), "1 - |sim - actual| / |literature - actual|", ["ctrip_perf_effect_sim", "ctrip_perf_effect_actual", "ctrip_perf_effect_literature"])
    sdv = A["performance_sd_value_share"] * A["average_salary_usd"]
    put("c2_sd_share", A["performance_sd_value_share"], pct(100 * A["performance_sd_value_share"]), "assumption", [])
    put("c2_sd_value", sdv, f"${sdv:,.0f}", "share x salary", [])
    gl, gs = abs(el - ea), abs(es - ea)
    put("c2_gap_literature", gl, f"{gl:.2f}", "|literature - actual|", ["ctrip_perf_effect_literature", "ctrip_perf_effect_actual"])
    put("c2_gap_sim", gs, f"{gs:.2f}", "|sim - actual|", ["ctrip_perf_effect_sim", "ctrip_perf_effect_actual"])
    ml, ms = gl * sdv * n, gs * sdv * n
    put("c2_misstated_literature", ml, usd(ml, 100000), "gap x SD value x firm", ["ctrip_perf_effect_literature", "ctrip_perf_effect_actual"])
    put("c2_misstated_sim", ms, usd(ms, 100000), "gap x SD value x firm", ["ctrip_perf_effect_sim", "ctrip_perf_effect_actual"])
    put("c2_value", ml - ms, usd(ml - ms), "difference", ["ctrip_perf_effect_sim", "ctrip_perf_effect_literature", "ctrip_perf_effect_actual"])

    # ---- 5. AI adoption by sector (BTOS)
    bs, bb, bm = inp["btos_ai_mae_sim"], inp["btos_ai_mae_best"], inp["btos_ai_mean_actual"]
    rb = 100 * (1 - bs / bb)
    put("c6_error_reduction", rb, pct(rb), "1 - sim MAE / best comparator MAE", ["btos_ai_mae_sim", "btos_ai_mae_best"])
    put("c6_acc_sim", 100 * (1 - bs / bm), pct(100 * (1 - bs / bm)), "100 x (1 - MAE / mean actual)", ["btos_ai_mae_sim", "btos_ai_mean_actual"])
    put("c6_mae_sim", bs, f"{bs:.2f}", "input", ["btos_ai_mae_sim"])
    put("c6_mae_best", bb, f"{bb:.2f}", "input", ["btos_ai_mae_best"])
    put("c6_mean_actual", bm, f"{bm:.2f}%", "input", ["btos_ai_mean_actual"])
    put("c6_mis_sim", 100 * bs / bm, pct(100 * bs / bm, 1), "MAE / mean actual", ["btos_ai_mae_sim", "btos_ai_mean_actual"])
    put("c6_mis_best", 100 * bb / bm, pct(100 * bb / bm, 1), "best MAE / mean actual", ["btos_ai_mae_best", "btos_ai_mean_actual"])
    seats = n * A["licence_seats_share"]
    put("c6_seats", seats, f"{seats:,.0f}", "firm x seat share", [])
    put("c6_price", inp["copilot_price_per_user_month"], f"${inp['copilot_price_per_user_month']:.0f}", "input", ["copilot_price_per_user_month"])
    lic = seats * inp["copilot_price_per_user_month"] * 12
    put("c6_budget", lic, usd(lic, 10000), "seats x price x 12", ["copilot_price_per_user_month"])
    put("c6_gap_points", 100 * (bb - bs) / bm, f"{100 * (bb - bs) / bm:.1f}", "difference in mis-provisioned share", ["btos_ai_mae_sim", "btos_ai_mae_best", "btos_ai_mean_actual"])
    v6 = lic * (bb - bs) / bm
    put("c6_value", v6, usd(v6), "licence budget x difference", ["btos_ai_mae_sim", "btos_ai_mae_best", "btos_ai_mean_actual", "copilot_price_per_user_month"])

    # ---- 6. demand after ChatGPT (Stack Overflow questions)
    ss, sb, sm = inp["so_chatgpt_mae_sim"], inp["so_chatgpt_mae_best"], inp["so_chatgpt_mean_actual"]
    put("c7_error_reduction", 100 * (1 - ss / sb), pct(100 * (1 - ss / sb)), "1 - sim MAE / best comparator MAE", ["so_chatgpt_mae_sim", "so_chatgpt_mae_best"])
    put("c7_acc_sim", 100 * (1 - ss / sm), pct(100 * (1 - ss / sm)), "100 x (1 - MAE / mean actual)", ["so_chatgpt_mae_sim", "so_chatgpt_mean_actual"])
    put("c7_mae_sim", ss, f"{ss:,.0f}", "input", ["so_chatgpt_mae_sim"])
    put("c7_mae_best", sb, f"{sb:,.0f}", "input", ["so_chatgpt_mae_best"])
    put("c7_mean_actual", sm, f"{round(sm / 100) * 100:,.0f}", "input", ["so_chatgpt_mean_actual"])
    g7 = 100 * (sb - ss) / sm
    put("c7_gap_pct", g7, pct(g7, 1), "(best MAE - sim MAE) / mean actual", ["so_chatgpt_mae_sim", "so_chatgpt_mae_best", "so_chatgpt_mean_actual"])
    put("c7_window", inp["so_chatgpt_window_weeks"], f"{inp['so_chatgpt_window_weeks']:.0f}", "input", ["so_chatgpt_window_weeks"])
    put("c7_cost", A["volume_linked_cost_usd"], "$1 million", "assumption", [])
    put("c7_value", g7 / 100 * A["volume_linked_cost_usd"], usd(g7 / 100 * A["volume_linked_cost_usd"]), "gap x volume-linked cost", ["so_chatgpt_mae_sim", "so_chatgpt_mae_best", "so_chatgpt_mean_actual"])

    # ---- 4. AI token budget (OpenRouter portfolio spend)
    miss_c = 100 * inp["or_spend_mae_best"] / inp["or_spend_actual_mean"]
    miss_s = 100 * inp["or_spend_mae_sim"] / inp["or_spend_actual_mean"]
    put("c4_backtests", inp["or_cutoffs"], f"{inp['or_cutoffs']:.0f}", "input", ["or_cutoffs"])
    put("c4_apps", inp["or_apps_per_cutoff"], f"{inp['or_apps_per_cutoff']:.0f}", "input", ["or_apps_per_cutoff"])
    put("c4_miss_classical", miss_c, pct(miss_c), "best standard MAE / mean actual spend", ["or_spend_mae_best", "or_spend_actual_mean"])
    put("c4_miss_sim", miss_s, pct(miss_s), "simulation MAE / mean actual spend", ["or_spend_mae_sim", "or_spend_actual_mean"])
    put("c4_miss_classical_1dp", miss_c, pct(miss_c, 1), "same, one decimal", ["or_spend_mae_best", "or_spend_actual_mean"])
    put("c4_miss_sim_1dp", miss_s, pct(miss_s, 1), "same, one decimal", ["or_spend_mae_sim", "or_spend_actual_mean"])
    put("c4_acc_sim", 100 - miss_s, pct(100 - miss_s), "100 - simulation miss", ["or_spend_mae_sim", "or_spend_actual_mean"])
    put("c4_acc_classical", 100 - miss_c, pct(100 - miss_c), "100 - classical miss", ["or_spend_mae_best", "or_spend_actual_mean"])
    r4 = 100 * (1 - inp["or_spend_mae_sim"] / inp["or_spend_mae_best"])
    put("c4_error_reduction", r4, pct(r4), "1 - simulation MAE / best standard MAE", ["or_spend_mae_sim", "or_spend_mae_best"])
    spend = A["annual_token_spend_usd"]
    put("c4_spend", spend, f"${spend:,}", "assumption", [])
    vc, vs = spend * miss_c / 100, spend * miss_s / 100
    put("c4_variance_classical", vc, f"${round(vc / 100) * 100:,.0f}", "spend x classical miss", ["or_spend_mae_best", "or_spend_actual_mean"])
    put("c4_variance_sim", vs, f"${round(vs / 100) * 100:,.0f}", "spend x simulation miss", ["or_spend_mae_sim", "or_spend_actual_mean"])
    put("c4_variance_gap_exact", vc - vs, f"${round((vc - vs) / 100) * 100:,.0f}", "difference", [])
    put("c4_variance_gap", vc - vs, usd(vc - vs), "difference, rounded", [])
    d = A["commitment_discount"]
    put("c4_discount", d, pct(100 * d), "assumption", [])
    pm = commitment_saving_per_million(d)
    put("c4_saving_per_million", pm, f"${pm:,.0f}", "commitment loss of best standard minus simulation, per $1M (portfolio)", ["or_spend_mae_sim"])
    put("c4_spend_in_millions", spend / 1e6, f"{spend / 1e6:.2f}", "spend / 1,000,000", [])
    put("c4_saving_exact", pm * spend / 1e6, f"${round(pm * spend / 1e6 / 100) * 100:,.0f}", "per million x spend in millions", [])
    put("c4_saving", pm * spend / 1e6, usd(pm * spend / 1e6), "same, rounded", [])
    put("c4_one_million", 1e6, "$1 million", "unit", [])
    put("c4_total", (vc - vs) + pm * spend / 1e6, usd((vc - vs) + pm * spend / 1e6), "budget variance gap + commitment saving", ["or_spend_mae_sim", "or_spend_mae_best", "or_spend_actual_mean"])

    # ---- 5. operations staffing (BPI 2019)
    exp = 100 * (1 / inp["bpi_no_expansion_multiplier"] - 1)
    put("c5_expansion", exp, pct(exp), "1 / no-expansion multiplier - 1", ["bpi_no_expansion_multiplier"])
    a5s = 100 * (1 - inp["bpi_completion_mae_sim"] / inp["bpi_completion_after_actual"])
    a5c = 100 * (1 - inp["bpi_completion_mae_best"] / inp["bpi_completion_after_actual"])
    put("c5_acc_sim", a5s, pct(a5s), "1 - simulation MAE / after-period completion", ["bpi_completion_mae_sim", "bpi_completion_after_actual"])
    put("c5_acc_classical", a5c, pct(a5c), "1 - best other MAE / after-period completion", ["bpi_completion_mae_best", "bpi_completion_after_actual"])
    put("c5_error_reduction", inp["bpi_completion_error_reduction"], pct(inp["bpi_completion_error_reduction"]), "input", ["bpi_completion_error_reduction"])
    put("c5_completion_observed", inp["bpi_alt_completion_observed"], pct(inp["bpi_alt_completion_observed"], 2), "input", ["bpi_alt_completion_observed"])
    put("c5_completion_no_expansion", inp["bpi_alt_completion_no_expansion"], pct(inp["bpi_alt_completion_no_expansion"], 2), "input", ["bpi_alt_completion_no_expansion"])
    after = A["ops_team_after_expansion"]
    before = after * inp["bpi_no_expansion_multiplier"]
    put("c5_team_before", before, f"{before:.0f}", "team after x no-expansion multiplier", ["bpi_no_expansion_multiplier"])
    put("c5_team_after", after, f"{after}", "assumption", [])
    put("c5_added", after - before, f"{after - before:.0f}", "after - before", ["bpi_no_expansion_multiplier"])
    put("c5_wage", inp["bls_clerk_median_wage"], f"${inp['bls_clerk_median_wage']:,.0f}", "input", ["bls_clerk_median_wage"])
    put("c5_wage_year", inp["bls_clerk_wage_year"], f"{inp['bls_clerk_wage_year']:.0f}", "input", ["bls_clerk_wage_year"])
    put("c5_value_exact", (after - before) * inp["bls_clerk_median_wage"], f"${(after - before) * inp['bls_clerk_median_wage']:,.0f}", "added roles x median wage", ["bls_clerk_median_wage"])
    put("c5_value", (after - before) * inp["bls_clerk_median_wage"], usd((after - before) * inp["bls_clerk_median_wage"], 10000), "same, rounded", ["bls_clerk_median_wage"])

    with (HERE / "sealed" / "case_numbers.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "value", "display", "formula", "inputs"])
        w.writeheader(); w.writerows(rows)
    print(f"wrote sealed/case_numbers.csv ({len(rows)} numbers)")


if __name__ == "__main__":
    main()
