"""Reader-facing summaries derived from saved evaluations, never hand-entered values."""
from __future__ import annotations

import json
from statistics import mean
import yaml

from .results import run_docs


def presentation_config(ctx):
    path = ctx.ui_dir / "presentation.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def presented_scenarios(ctx):
    from ..scenarios import list_scenarios
    cards = presentation_config(ctx).get("cards", {})
    scenarios = list_scenarios(ctx)
    for item in scenarios:
        document = yaml.safe_load((ctx.scenarios_dir / item["file"]).read_text()) or {}
        if item["role"] == "other" and document.get("created_in_ui"):
            item["role"] = "custom"
        card = cards.get(item["id"], {})
        item["display_title"] = card.get("title", item["short_title"])
        item["card_summary"] = card.get("summary", item.get("summary", ""))
    return scenarios


def insights_document(ctx, result):
    cfg = presentation_config(ctx)
    evaluation = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    spec = cfg.get("primary", {})
    primary = {k: spec[k] for k in ("label", "unit", "subject") if k in spec}
    if spec.get("held_out"):
        protocol = evaluation["protocol"]
        rows = [r for r in evaluation["rows"] if r["cutoff"] not in protocol["dev_cutoffs"]
                and r["block"] in protocol["headline_blocks"] and (not spec.get("group") or r["group"] == spec["group"])]
        accuracy = evaluation["accuracy"]["held_out"]["headline"]
        other = accuracy["best_baseline"]
        scale = protocol.get("scale", 1)
        primary.update(actual=mean(r["actual"] for r in rows) * scale,
                       simulation=mean(r["simulation"] for r in rows) * scale,
                       other=mean(r[other] for r in rows) * scale,
                       other_label={"bass_diffusion": "Adoption curve", "holt_damped": "Damped trend", "carry_forward": "No change"}.get(other, other.replace("_", " ")))
        primary["error"] = {"simulation": evaluation["headline"]["mae"]["simulated"],
                            "other": evaluation["headline"]["mae"]["baseline"],
                            "unit": evaluation["headline"]["mae"]["unit"],
                            "scope": "Average error across all scored groups and periods"}
    elif spec.get("story"):
        story = result["story"]
        metric = next(m for m in story["metrics"] if m["id"] == spec["story"])
        other = next(b for b in story["baselines"] if b["id"] == spec["other"])
        primary.update(actual=metric["after_actual"], simulation=metric["after_sim"],
                       other=other["values"].get(spec["story"]), other_label=other.get("label", other.get("title", spec["other"].replace("_", " "))))
        if story.get("baseline_basis") == "effect":
            level = story.get("level_comparison", {})
            primary["other"] = next((p["value"] for p in level.get("predictions", []) if p["label"] == primary["other_label"]), None)
        business = next((m for m in evaluation.get("business_validation", []) if m["id"] == spec["story"]), None)
        if business:
            primary["error"] = {"simulation": business["simulation_mae"], "other": business["baseline_mae"][spec["other"]],
                                "unit": "pp" if spec["unit"] == "%" else spec["unit"], "scope": "Average error across prediction dates"}
            primary["averaged"] = True
    else:
        metric = next((m for m in result.get("metrics", []) if m["values"].get("actual") is not None), None)
        if metric:
            primary.update(label=metric["label"], unit=metric["unit"], subject=metric["label"].lower(),
                           actual=metric["values"]["actual"], simulation=metric["values"].get("baseline"), other=None, other_label="Not available")

    alternative = result.get("scenarios", {}).get("alternative")
    alternatives = []
    if alternative:
        metrics = []
        for mid in cfg.get("alternatives", []):
            m = next((m for m in result["metrics"] if m["id"] == mid), None)
            if m and m["values"].get("alternative") is not None:
                metrics.append({"label": m["label"], "unit": "$m" if mid == "coding_spend" else m["unit"],
                                "reference": m.get("paired_baseline", m["values"].get("baseline")),
                                "value": m["values"]["alternative"], "better": m.get("better")})
        if cfg.get("alternative_groups"):
            metrics = adoption_alternatives(ctx, evaluation, alternative["id"], cfg["alternative_groups"])
        alternatives.append({"id": alternative["id"], "title": cfg.get("cards", {}).get(alternative["id"], {}).get("title", alternative["short_title"]),
                             "metrics": metrics, "note": "Simulated alternative, compared with its matched reference runs."})
    for view in result.get("explorations", []):
        if view.get("state") != "ready":
            alternatives.append({"id": view["id"], "title": view["title"], "metrics": [], "note": "Saved comparison needs refreshing."})
            continue
        selected = [m for m in view["metrics"] if m["id"] in ("effort_reduction", "human_hours", "completion")]
        alternatives.append({"id": view["id"], "title": cfg.get("cards", {}).get(view["id"], {}).get("title", view["title"]),
                             "metrics": [{"label": {"effort_reduction": "Staff effort released", "human_hours": "Modeled human hours saved"}.get(m["id"], m["label"]),
                                          "unit": m["unit"], "reference": m["baseline"], "value": m["alternative"], "better": m.get("better"),
                                          "is_change": m["id"] == "effort_reduction", "reverse_delta": m["id"] == "human_hours",
                                          "display_threshold": 0.1 if m["id"] == "completion" else 0.005} for m in selected[:2]],
                             "note": "Assumption-based AI scenario; released staff time is not a measured cash saving."})
    return {"primary": primary, "caveat": cfg.get("caveat", ""), "alternatives": alternatives,
            "context": ctx.meta.get("situation", ctx.meta.get("problem", ""))}


def adoption_alternatives(ctx, evaluation, sid, groups):
    """Compare matching cutoffs/seeds; never use the invariant mean of shares."""
    ids = evaluation.get("run_ids", {})
    reference = run_docs(ctx, "baseline", "summary", ids.get("baseline", []))
    alternatives = run_docs(ctx, sid, "summary", ids.get(sid, []))
    key = lambda d: (d["headline"]["cutoff"], d["seed"])
    refs = {key(d): d for d in reference}
    pairs = [(refs[key(d)]["headline"], d["headline"]) for d in alternatives if key(d) in refs]
    metrics = []
    for gid in groups:
        values, labels = [], []
        for a, b in pairs:
            ga = next((g for g in a["groups"] if g["group"] == gid), None)
            gb = next((g for g in b["groups"] if g["group"] == gid), None)
            if not ga or not gb:
                continue
            if a["outcome"] == "displaced":
                values.append((sum(ga["central"]), sum(gb["central"])))
                labels.append((f"Questions over the next {a['horizon_periods']} weeks", "questions"))
            else:
                values.append((100 * ga["central"][-1], 100 * gb["central"][-1]))
                labels.append((f"{gb['label']} · share at period {a['horizon_periods']}", "%"))
        if values:
            metrics.append({"label": labels[0][0], "unit": labels[0][1], "reference": mean(a for a, _ in values), "value": mean(b for _, b in values)})
    return metrics
