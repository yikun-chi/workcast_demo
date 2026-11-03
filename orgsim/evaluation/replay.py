"""Compact playback frames from the saved event log; no simulation or interpolation."""
from __future__ import annotations

from datetime import datetime
import pandas as pd


def event_replay(reader, agent: str = "", org_unit: str = "", role: str = "") -> dict:
    filters = [(field, "=", value) for field, value in
               (("agent_id", agent), ("org_unit", org_unit), ("role", role)) if value]
    trace = reader.trace(filters=filters or None)
    columns = list(trace.columns)
    index = {key: i for i, key in enumerate(columns)}
    frames = {}
    for row in trace.itertuples(index=False, name=None):
        tick, time, who = row[index["tick"]], row[index["sim_time"]], row[index["agent_id"]]
        frame = frames.setdefault(tick, {"tick": tick, "time": time, "total": 0, "entities": set(), "groups": {}})
        frame["total"] += 1
        frame["time"] = min(frame["time"], time)
        if who:
            frame["entities"].add(who)
        activity, action = row[index["activity"]], row[index["action_type"]]
        group = frame["groups"].setdefault((activity, action), {"activity": activity, "action_type": action, "count": 0, "sample": row})
        group["count"] += 1

    def scalar(value):
        if isinstance(value, datetime):
            return value.isoformat(timespec="milliseconds")
        return None if pd.isna(value) else value

    output = []
    for tick, frame in sorted(frames.items()):
        groups = sorted(frame["groups"].values(), key=lambda c: (-c["count"], c["activity"], c["action_type"]))
        output.append({"tick": int(tick), "time": scalar(frame["time"]), "total": frame["total"], "entities": len(frame["entities"]),
                       "activities": [{k: g[k] for k in ("activity", "action_type", "count")} for g in groups],
                       "samples": [{key: scalar(value) for key, value in zip(columns, g["sample"])} for g in groups[:8]]})
    return {"run_id": reader.run_id, "scenario": reader.scenario, "agent": agent, "org_unit": org_unit, "role": role,
            "total": len(trace), "frames": output,
            "note": "Each step is a recorded simulation time. Quiet gaps are skipped; pulses summarize events, not individual people. Preview cards are examples; counts include every matching saved event."}
