"""FastAPI server: one API for every instance, plus the static UI shell and instance UI plugins.

Endpoints (all JSON unless noted):
  GET  /api/health
  GET  /api/onet/summary | /api/onet/occupations/{code} | /api/onet/dwas?q=
  GET  /api/instances
  GET  /api/instances/{id}                      instance.yaml + counts + plugin pages
  GET  /api/instances/{id}/ontology?tasks=0|1   bindings graph merged with O*NET subgraphs
  GET  /api/instances/{id}/ontology/schema      the ontology schema itself as a graph
  GET  /api/instances/{id}/ontology/concepts    concept graph as used by this instance: definitions, counts, used flags (Ontology tab, Concepts view)
  GET  /api/instances/{id}/ontology/bindings    raw bindings.yaml as JSON        PUT to save (Input tab)
  GET  /api/instances/{id}/summary              instances/<id>/data/normalized/summary.json (company data)
  GET  /api/instances/{id}/tables               list of tables (parquet/csv/json under data/normalized)
  GET  /api/instances/{id}/tables/{name}?offset&limit&q&sort&desc
  GET  /api/instances/{id}/people?offset&limit&q&sort&desc&group   the people of the instance (Data tab, People view)
  GET  /api/instances/{id}/people/graph         groups (units, teams, roles, locations), their links, person-link counts
  GET  /api/instances/{id}/people/{pid}/ego?limit   one person's neighbourhood as a typed graph (teammates or hand-off partners)
  GET  /api/instances/{id}/scenarios            list;  GET /scenarios/{sid} resolved;  PUT /scenarios/{sid} save raw yaml dict
  GET  /api/instances/{id}/seats                policies/seats.yaml           PUT to save
  GET  /api/instances/{id}/runs                 all runs;  POST {scenario, seed} launches one in the background
  POST /api/instances/{id}/explorations         {scenario} launches a matched alternative comparison
  GET  /api/instances/{id}/exploration-status   background comparison status
  GET  /api/instances/{id}/runs/{sid}/{run}/summary|config|metrics
  GET  /api/instances/{id}/runs/{sid}/{run}/trace?offset&limit&agent&org_unit&role&case&activity&action&from_tick&to_tick
  GET  /api/instances/{id}/runs/{sid}/{run}/timeline?by=activity|role|action_type&bucket=1  (counts per tick bucket)
  GET  /api/instances/{id}/runs/{sid}/{run}/agents    per-agent activity counts
  GET  /api/instances/{id}/runs/{sid}/{run}/twins     digital twins (workforce worlds): profile, traits, final states; ?agent= filters one
  GET  /api/instances/{id}/evaluation           runs/<id>/evaluation.json (predicted vs actual vs baselines, charts)
  GET  /api/instances/{id}/results              evaluation comparisons for Insights (world results_view)
  GET  /api/instances/{id}/insights-summary     concise comparison punchlines
  GET  /api/instances/{id}/scenario-results     scenario cards with selected saved runs
  GET  /api/instances/{id}/runs/{sid}/{run}/history   saved metrics, paths, entities and configuration
  GET  /api/instances/{id}/runs/{sid}/{run}/replay?agent&org_unit&role   ordered saved-event frames; no simulation
  POST /api/instances/{id}/scenarios            create {id, title, description, extends}; never overwrite
  GET  /api/instances/{id}/insights             runs/<id>/insights.json (simulated interviews, topics, sentiment); POST {n, model} regenerates it
  GET  /api/instances/{id}/report               instances/<id>/reports/report.json
  GET  /instances/{id}/ui/*                     instance plugin static files
  GET  /                                        ui/index.html (shell); /ui/* static
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import REPO_ROOT, RUNS_DIR, UI_DIR
from ..instances import InstanceContext, get_instance, list_instances
from ..ontology import onet
from ..ontology import people as people_mod
from ..ontology.bindings import build_graph, validate
from ..ontology.schema import schema_graph
from ..ontology.system import instance_concepts
from ..scenarios import list_scenarios, load_scenario, scenario_roles
from ..composition import instance_service
from ..store import RunReader, list_runs

app = FastAPI(title="orgsim", version="0.1.0")
UI_VERSION = str(int(max(p.stat().st_mtime for p in UI_DIR.rglob("*") if p.is_file())))   # changes whenever a UI file changes


@app.middleware("http")
async def _no_ui_cache(request, call_next):
    """The UI is build-free ES modules; browsers would otherwise keep stale pages for hours after an update."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/ui/") or "/ui/" in path:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def _ctx(instance_id: str) -> InstanceContext:
    try:
        return get_instance(instance_id)
    except KeyError:
        raise HTTPException(404, f"unknown instance {instance_id}")


def _json_file(p: Path) -> Any:
    if not p.exists():
        raise HTTPException(404, f"missing {p.relative_to(REPO_ROOT)}")
    return json.loads(p.read_text())


def _plugins(ctx: InstanceContext) -> list[dict[str, Any]]:
    p = ctx.ui_dir / "pages.json"
    if not p.exists():
        return []
    pages = json.loads(p.read_text())
    for pg in pages:
        pg["url"] = f"/instances/{ctx.id}/ui/{pg['entry']}"
    return pages


def _clean(obj: Any) -> Any:
    """Make pandas/numpy values JSON-safe."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        return None if obj != obj else obj
    if hasattr(obj, "item"):
        v = obj.item(); return None if isinstance(v, float) and v != v else v
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "instances": [i.id for i in list_instances()]}


@app.get("/api/onet/summary")
def onet_summary() -> dict:
    return onet.summary()


@app.get("/api/onet/occupations/{code}")
def onet_occupation(code: str) -> dict:
    try:
        return onet.occupation(code)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/onet/dwas")
def onet_dwas(q: str = Query("", min_length=0), limit: int = 25) -> list[dict]:
    return onet.search_dwas(q, limit) if q else []


@app.get("/api/instances")
def instances() -> list[dict]:
    out = []
    for i in list_instances():
        runs = list_runs(i.id)
        hero = None
        try:
            hero = instance_service(i).results().get("hero")
        except Exception:  # noqa: BLE001  (no evaluation yet: the card shows the problem and the intro only)
            hero = None
        scenarios = list_scenarios(i)
        alternatives = [s for s in scenarios if s["role"].startswith("alternative")]
        alt = next((s for s in alternatives if s["role"] == "alternative"), None)
        out.append({**i.meta, "id": i.id, "hero": hero, "alternative": alt, "alternatives": alternatives, "n_runs": len(runs), "n_scenarios": len(scenarios),
                    "has_report": (i.reports_dir / "report.json").exists(), "has_evaluation": (RUNS_DIR / i.id / "evaluation.json").exists(),
                    "has_insights": (RUNS_DIR / i.id / "insights.json").exists(),
                    "plugins": _plugins(i)})
    return out


@app.get("/api/instances/{instance_id}")
def instance(instance_id: str) -> dict:
    ctx = _ctx(instance_id)
    return {**ctx.meta, "id": ctx.id, "plugins": _plugins(ctx), "scenarios": list_scenarios(ctx), "scenario_roles": scenario_roles(ctx), "n_runs": len(list_runs(ctx.id)),
            "has_report": (ctx.reports_dir / "report.json").exists(), "has_evaluation": (RUNS_DIR / ctx.id / "evaluation.json").exists(),
            "has_insights": (RUNS_DIR / ctx.id / "insights.json").exists(), "bindings_problems": validate(ctx)}


@app.get("/api/instances/{instance_id}/ontology")
def ontology(instance_id: str, tasks: int = 0) -> dict:
    return build_graph(_ctx(instance_id), include_onet=True, include_tasks=bool(tasks)).to_json()


@app.get("/api/instances/{instance_id}/ontology/schema")
def ontology_schema(instance_id: str) -> dict:
    return schema_graph().to_json()


@app.get("/api/instances/{instance_id}/ontology/concepts")
def ontology_concepts(instance_id: str) -> dict:
    return instance_concepts(_ctx(instance_id))


@app.get("/api/instances/{instance_id}/ontology/bindings")
def bindings(instance_id: str) -> dict:
    ctx = _ctx(instance_id)
    if not (ctx.ontology_dir / "bindings.yaml").exists():
        raise HTTPException(404, "no ontology/bindings.yaml")
    return ctx.yaml("ontology/bindings.yaml")


@app.put("/api/instances/{instance_id}/ontology/bindings")
def save_bindings(instance_id: str, body: dict) -> dict:
    ctx = _ctx(instance_id)
    ctx.ontology_dir.mkdir(exist_ok=True)
    (ctx.ontology_dir / "bindings.yaml").write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return {"saved": True, "problems": validate(ctx)}


@app.get("/api/instances/{instance_id}/summary")
def summary(instance_id: str) -> Any:
    return _json_file(_ctx(instance_id).data_normalized / "summary.json")


def _tables(ctx: InstanceContext) -> dict[str, Path]:
    out: dict[str, Path] = {}
    base = ctx.data_normalized
    if base.exists():
        for p in sorted(base.rglob("*")):
            if p.is_dir() and p.suffix == ".parquet":
                out[p.relative_to(base).as_posix()] = p
            elif p.is_file() and p.suffix in (".parquet", ".csv") and not any(x.suffix == ".parquet" for x in p.parents if x != base):
                out[p.relative_to(base).as_posix()] = p
    return out


_TABLE_CACHE: dict[tuple, pd.DataFrame] = {}
_TABLE_CACHE_MAX = 12


def _mtime(p: Path) -> float:
    if p.is_dir():
        return max((f.stat().st_mtime for f in p.rglob("*") if f.is_file()), default=0.0)
    return p.stat().st_mtime


def _cached_frame(p: Path, loader) -> pd.DataFrame:
    key = (str(p), _mtime(p))
    df = _TABLE_CACHE.get(key)
    if df is None:
        df = loader()
        for k in [k for k in _TABLE_CACHE if k[0] == str(p)]:
            _TABLE_CACHE.pop(k, None)
        if len(_TABLE_CACHE) >= _TABLE_CACHE_MAX:
            _TABLE_CACHE.pop(next(iter(_TABLE_CACHE)))
        _TABLE_CACHE[key] = df
    return df


def _read_table(p: Path, columns: list[str] | None = None) -> pd.DataFrame:
    def load() -> pd.DataFrame:
        if p.suffix == ".csv":
            return pd.read_csv(p)
        import pyarrow.parquet as pq
        return pq.read_table(p).to_pandas()
    df = _cached_frame(p, load)
    return df[columns] if columns else df


@app.get("/api/instances/{instance_id}/tables")
def tables(instance_id: str) -> list[dict]:
    ctx = _ctx(instance_id)
    out = []
    for name, p in _tables(ctx).items():
        try:
            if p.suffix == ".csv":
                df = pd.read_csv(p); n = len(df)
                cols = list(df.columns)
                schema = [{"name": c, "type": str(df[c].dtype), "nullable": bool(df[c].isna().any())} for c in cols]
            else:
                import pyarrow.parquet as pq
                if p.is_dir():
                    ds = pq.ParquetDataset(p); n = sum(f.metadata.num_rows for f in (pq.ParquetFile(x) for x in ds.files)); arrow_schema = ds.schema
                else:
                    pf = pq.ParquetFile(p); n = pf.metadata.num_rows; arrow_schema = pf.schema_arrow
                cols = arrow_schema.names
                schema = [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in arrow_schema]
            out.append({"name": name, "rows": int(n), "columns": cols, "schema": schema})
        except Exception as e:  # noqa: BLE001
            out.append({"name": name, "error": str(e)})
    return out


@app.get("/api/instances/{instance_id}/tables/{name:path}")
def table_rows(instance_id: str, name: str, offset: int = 0, limit: int = Query(50, le=1000), q: str = "", sort: str = "", desc: int = 0) -> dict:
    ctx = _ctx(instance_id)
    t = _tables(ctx)
    if name not in t:
        raise HTTPException(404, f"unknown table {name}")
    df = _read_table(t[name])
    if q:
        mask = pd.Series(False, index=df.index)
        for c in df.columns:
            mask |= df[c].astype(str).str.contains(q, case=False, regex=False, na=False)
        df = df[mask]
    if sort and sort in df.columns:
        df = df.sort_values(sort, ascending=not desc, kind="stable")
    page = df.iloc[offset: offset + limit]
    return {"name": name, "total": int(len(df)), "offset": offset, "limit": limit, "columns": list(df.columns),
            "rows": _clean(json.loads(page.to_json(orient="records", date_format="iso")))}


def _people_error(e: Exception) -> HTTPException:
    return HTTPException(404, f"no people view: {e}")


@app.get("/api/instances/{instance_id}/people")
def people_rows(instance_id: str, offset: int = 0, limit: int = Query(50, le=1000), q: str = "", sort: str = "", desc: int = 0, group: str = "") -> dict:
    try:
        return people_mod.people_page(_ctx(instance_id), offset=offset, limit=limit, q=q, sort=sort, desc=bool(desc), group=group)
    except (FileNotFoundError, KeyError) as e:
        raise _people_error(e)


@app.get("/api/instances/{instance_id}/people/graph")
def people_graph(instance_id: str) -> dict:
    try:
        return people_mod.people_graph(_ctx(instance_id))
    except (FileNotFoundError, KeyError) as e:
        raise _people_error(e)


@app.get("/api/instances/{instance_id}/people/{person_id}/ego")
def people_ego(instance_id: str, person_id: str, limit: int = Query(40, le=500)) -> dict:
    try:
        return people_mod.ego_graph(_ctx(instance_id), person_id, limit=limit)
    except FileNotFoundError as e:
        raise _people_error(e)
    except KeyError:
        raise HTTPException(404, f"unknown person {person_id}")


@app.get("/api/instances/{instance_id}/scenarios")
def scenarios(instance_id: str) -> list[dict]:
    from ..evaluation.presentation import presented_scenarios
    return presented_scenarios(_ctx(instance_id))


@app.get("/api/instances/{instance_id}/scenarios/{sid}")
def scenario(instance_id: str, sid: str) -> dict:
    try:
        return load_scenario(_ctx(instance_id), sid)
    except FileNotFoundError:
        raise HTTPException(404, f"unknown scenario {sid}")


@app.post("/api/instances/{instance_id}/scenarios")
def create_scenario(instance_id: str, body: dict) -> dict:
    import re
    ctx = _ctx(instance_id)
    sid = str(body.get("id", ""))
    parent = str(body.get("extends", "baseline"))
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", sid) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", parent):
        raise HTTPException(400, "Use a scenario name with letters, numbers, hyphens or underscores")
    title = str(body.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "Enter a title for the scenario")
    try:
        load_scenario(ctx, parent)
    except FileNotFoundError:
        raise HTTPException(404, "The starting scenario does not exist")
    document = {"id": sid, "title": title, "short_title": title, "description": str(body.get("description", "")),
                "summary": str(body.get("description", "")), "extends": parent, "created_in_ui": True}
    ctx.scenarios_dir.mkdir(exist_ok=True)
    try:
        with (ctx.scenarios_dir / f"{sid}.yaml").open("x") as stream:
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
    except FileExistsError:
        raise HTTPException(409, "That scenario already exists; choose another name")
    return {"created": True, "id": sid}


@app.put("/api/instances/{instance_id}/scenarios/{sid}")
def save_scenario(instance_id: str, sid: str, body: dict) -> dict:
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", sid):
        raise HTTPException(400, "Invalid scenario name")
    ctx = _ctx(instance_id)
    ctx.scenarios_dir.mkdir(exist_ok=True)
    body["id"] = sid
    parent = body.get("extends")
    if parent and parent != sid:
        try:
            base = load_scenario(ctx, parent)
            body = {k: v for k, v in body.items() if k in ("id", "extends", "created_in_ui", "title", "short_title", "summary", "description") or base.get(k) != v}
        except FileNotFoundError:
            pass
    if any(iv.get("type") == "ai_assist" for iv in body.get("interventions", [])):
        from ..scenarios.assistance import assistance_by_activity
        try:
            assistance_by_activity(body["interventions"], {a["id"] for a in ctx.yaml("ontology/bindings.yaml")["activities"]})
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
    (ctx.scenarios_dir / f"{sid}.yaml").write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return {"saved": True, "stored_keys": sorted(body)}


@app.get("/api/instances/{instance_id}/seats")
def seats(instance_id: str) -> dict:
    return _ctx(instance_id).yaml("policies/seats.yaml")


@app.put("/api/instances/{instance_id}/seats")
def save_seats(instance_id: str, body: dict) -> dict:
    ctx = _ctx(instance_id)
    ctx.policies_dir.mkdir(exist_ok=True)
    (ctx.policies_dir / "seats.yaml").write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return {"saved": True}


@app.get("/api/instances/{instance_id}/runs")
def runs(instance_id: str) -> list[dict]:
    return list_runs(_ctx(instance_id).id)


@app.get("/api/instances/{instance_id}/exploration-status")
def exploration_status(instance_id: str) -> dict:
    path = _ctx(instance_id).runs_dir / "exploration_status.json"
    return json.loads(path.read_text()) if path.exists() else {"state": "idle"}


@app.post("/api/instances/{instance_id}/explorations")
def launch_exploration(instance_id: str, body: dict) -> dict:
    import uuid
    from ..evaluation.exploration import _save
    from ..scenarios.assistance import assistance_by_activity
    ctx = _ctx(instance_id)
    sid = body.get("scenario")
    if sid not in (ctx.meta.get("scenarios") or {}).get("additional_alternatives", []):
        raise HTTPException(400, "Choose a named additional alternative")
    scenario = load_scenario(ctx, sid)
    try:
        assistance_by_activity(scenario.get("interventions") or [], {a["id"] for a in ctx.yaml("ontology/bindings.yaml")["activities"]})
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if not (ctx.runs_dir / "evaluation.json").exists():
        raise HTTPException(400, "Run the reference evaluation first")
    if (ctx.runs_dir / ".exploration.lock").exists():
        raise HTTPException(409, "A comparison is already running for this instance")
    job_id = uuid.uuid4().hex
    status_path = ctx.runs_dir / "exploration_status.json"
    status = {"job_id": job_id, "scenario": sid, "state": "queued"}
    _save(status_path, status)
    try:
        with open(ctx.runs_dir / "exploration.log", "ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "orgsim.cli", "explore", ctx.id, "--scenario", sid, "--job-id", job_id],
                                    cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
    except OSError as error:
        _save(status_path, {**status, "state": "failed", "error": str(error)})
        raise HTTPException(500, "Could not start the comparison") from error
    return {**status, "pid": proc.pid}


@app.post("/api/instances/{instance_id}/runs")
def launch_run(instance_id: str, body: dict) -> dict:
    ctx = _ctx(instance_id)
    scenario_id = body.get("scenario", "baseline"); seed = int(body.get("seed", 1))
    cmd = [sys.executable, "-m", "orgsim.cli", "run", ctx.id, "--scenario", scenario_id, "--seed", str(seed)]
    log = RUNS_DIR / ctx.id / scenario_id; log.mkdir(parents=True, exist_ok=True)
    with open(log / "launch.log", "ab") as fh:
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT)
    return {"launched": True, "pid": proc.pid, "scenario": scenario_id, "seed": seed}


def _trace(r: RunReader) -> pd.DataFrame:
    return _cached_frame(r.dir / "trace.parquet", lambda: r.trace())


def _apply_filters(df: pd.DataFrame, agent: str, case: str, activity: str, from_tick: int, to_tick: int) -> pd.DataFrame:
    if agent: df = df[df["agent_id"] == agent]
    if case: df = df[df["case_id"] == case]
    if activity: df = df[df["activity"] == activity]
    if from_tick >= 0: df = df[df["tick"] >= from_tick]
    if to_tick >= 0: df = df[df["tick"] <= to_tick]
    return df


def _reader(instance_id: str, sid: str, run: str) -> RunReader:
    ctx = _ctx(instance_id)
    if run == "latest":
        from ..store import latest_run
        run = latest_run(ctx.id, sid) or ""
    try:
        return RunReader(ctx.id, sid, run)
    except FileNotFoundError:
        raise HTTPException(404, f"unknown run {sid}/{run}")


@app.get("/api/instances/{instance_id}/runs/{sid}/{run}/{name}")
def run_file(instance_id: str, sid: str, run: str, name: str, offset: int = 0, limit: int = Query(200, le=5000),
             agent: str = "", case: str = "", activity: str = "", from_tick: int = -1, to_tick: int = -1, by: str = "activity", bucket: int = 1,
             q: str = "", sort: str = "", desc: int = 0, action: str = "", org_unit: str = "", role: str = "") -> Any:
    r = _reader(instance_id, sid, run)
    if name == "replay":
        from ..evaluation.replay import event_replay
        return event_replay(r, agent, org_unit, role)
    if name == "history":
        from ..evaluation.history import run_history
        return run_history(_ctx(instance_id), r)
    if name in ("summary", "config", "metrics"):
        data = r.json(f"{name}.json")
        if data is None:
            raise HTTPException(404, f"no {name}.json")
        return data
    if name == "trace":
        df = _apply_filters(_trace(r), agent, case, activity, from_tick, to_tick)
        if action:
            df = df[df.action_type == action]
        for field, value in (("org_unit", org_unit), ("role", role)):
            if value:
                df = df[df[field] == value]
        if q:
            mask = pd.Series(False, index=df.index)
            for column in df.columns:
                mask |= df[column].astype(str).str.contains(q, case=False, regex=False, na=False)
            df = df[mask]
        if sort in df.columns:
            df = df.sort_values(sort, ascending=not desc, kind="stable", na_position="last")
        page = df.iloc[offset: offset + limit]
        return {"total": int(len(df)), "offset": offset, "limit": limit, "columns": list(df.columns),
                "rows": _clean(json.loads(page.to_json(orient="records", date_format="iso")))}
    if name == "timeline":
        df = _trace(r)[["tick", "sim_time", by]].copy()
        df["bucket"] = (df["tick"] // max(1, bucket)) * max(1, bucket)
        piv = df.groupby(["bucket", by]).size().unstack(fill_value=0)
        times = df.groupby("bucket")["sim_time"].min()
        return {"by": by, "bucket": bucket, "ticks": [int(x) for x in piv.index], "times": [t.isoformat() for t in times.reindex(piv.index)],
                "series": {str(c): [int(v) for v in piv[c].tolist()] for c in piv.columns}}
    if name == "twins":                       # digital-twin table written by workforce worlds (profile, traits, final states)
        data = r.json("twins.json")
        if data is None:
            raise HTTPException(404, "this run has no twins.json (not a workforce world)")
        rows = data.get("twins", [])
        if agent:
            rows = [t for t in rows if t.get("agent_id") == agent]
        return {"total": len(rows), "offset": offset, "limit": limit, "trait_keys": data.get("trait_keys", []), "rows": rows[offset: offset + limit]}
    if name == "agents":
        df = _trace(r)[["agent_id", "role", "org_unit", "activity", "action_type", "duration_h", "wait_h"]]
        g = df.groupby(["agent_id", "role", "org_unit"]).agg(events=("activity", "size"), hours=("duration_h", "sum"), wait=("wait_h", "sum")).reset_index()
        top = df.groupby(["agent_id", "activity"]).size().reset_index(name="n").sort_values("n", ascending=False).groupby("agent_id").head(5)
        acts = top.groupby("agent_id").apply(lambda x: dict(zip(x.activity, x.n.astype(int))), include_groups=False).to_dict()
        rows = _clean(json.loads(g.sort_values("events", ascending=False).to_json(orient="records")))
        for row in rows:
            row["top_activities"] = acts.get(row["agent_id"], {})
        return {"total": len(rows), "rows": rows[offset: offset + limit]}
    raise HTTPException(404, f"unknown run resource {name}")


@app.get("/api/instances/{instance_id}/evaluation")
def evaluation(instance_id: str) -> Any:
    return _json_file(RUNS_DIR / _ctx(instance_id).id / "evaluation.json")


@app.get("/api/instances/{instance_id}/results")
def results(instance_id: str) -> dict:
    ctx = _ctx(instance_id)
    try:
        return instance_service(ctx).results()
    except FileNotFoundError as e:
        raise HTTPException(404, f"results need an evaluation and runs: {e}")


@app.get("/api/instances/{instance_id}/insights-summary")
def insights_summary(instance_id: str) -> dict:
    from ..evaluation.presentation import insights_document
    ctx = _ctx(instance_id)
    try:
        return insights_document(ctx, instance_service(ctx).results())
    except FileNotFoundError as error:
        raise HTTPException(404, "Insights needs a saved evaluation and runs") from error


@app.get("/api/instances/{instance_id}/scenario-results")
def scenario_results(instance_id: str) -> list[dict]:
    from ..evaluation.history import scenario_catalog
    return scenario_catalog(_ctx(instance_id))


@app.get("/api/instances/{instance_id}/insights")
def insights(instance_id: str) -> Any:
    ctx = _ctx(instance_id)
    return _json_file(RUNS_DIR / ctx.id / "insights.json")


@app.post("/api/instances/{instance_id}/insights")
def insights_build(instance_id: str, body: dict | None = None) -> dict:
    from ..insights import build_insights
    ctx = _ctx(instance_id)
    body = body or {}
    return build_insights(ctx, n_per_scenario=int(body.get("n", 24)), model=body.get("model") or None)


@app.get("/api/instances/{instance_id}/report")
def report(instance_id: str) -> Any:
    return _json_file(_ctx(instance_id).reports_dir / "report.json")


# ---- static: instance plugins and the shell ----
for _inst in list_instances():
    if _inst.ui_dir.exists():
        app.mount(f"/instances/{_inst.id}/ui", StaticFiles(directory=_inst.ui_dir), name=f"ui-{_inst.id}")

if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


@app.get("/")
def index() -> Any:
    p = UI_DIR / "index.html"
    if not p.exists():
        return JSONResponse({"message": "UI not built yet; API is live at /api", "docs": "/docs"})
    from fastapi.responses import HTMLResponse
    html = p.read_text().replace('/ui/app.js"', f'/ui/app.js?v={UI_VERSION}"').replace('/ui/theme.css"', f'/ui/theme.css?v={UI_VERSION}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
