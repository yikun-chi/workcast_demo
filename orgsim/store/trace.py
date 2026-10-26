"""Canonical trace event emitted by every world. One schema for all instances; Parquet on disk."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

TRACE_COLUMNS = [
    "tick", "sim_time", "agent_id", "role", "org_unit", "case_id", "activity", "action_type",
    "duration_h", "wait_h", "provenance", "attributes",
]

# action_type vocabulary
ACTIONS = ("start", "complete", "handoff", "wait", "decide", "arrive", "state", "message", "exogenous")
# provenance vocabulary
PROVENANCE = ("simulated", "replayed", "exogenous")


@dataclass
class TraceEvent:
    tick: int
    sim_time: datetime
    activity: str
    action_type: str = "complete"
    agent_id: str = ""
    role: str = ""
    org_unit: str = ""
    case_id: str = ""
    duration_h: float = 0.0
    wait_h: float = 0.0
    provenance: str = "simulated"
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["attributes"] = json.dumps(self.attributes, default=str) if self.attributes else "{}"
        return d
