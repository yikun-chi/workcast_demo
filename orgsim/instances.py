"""Instance discovery and paths. An instance is a folder under instances/ with instance.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import INSTANCES_DIR, RUNS_DIR


@dataclass(frozen=True)
class InstanceContext:
    id: str
    root: Path
    meta: dict[str, Any]

    @property
    def data_raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def data_normalized(self) -> Path:
        return self.root / "data" / "normalized"

    @property
    def ontology_dir(self) -> Path:
        return self.root / "ontology"

    @property
    def policies_dir(self) -> Path:
        return self.root / "policies"

    @property
    def calibration_dir(self) -> Path:
        return self.root / "calibration"

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"

    @property
    def evaluation_dir(self) -> Path:
        return self.root / "evaluation"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def ui_dir(self) -> Path:
        return self.root / "ui"

    @property
    def runs_dir(self) -> Path:
        return RUNS_DIR / self.id

    @property
    def world_type(self) -> str:
        return str(self.meta.get("world_type", ""))

    def yaml(self, relpath: str) -> dict[str, Any]:
        p = self.root / relpath
        if not p.exists():
            return {}
        return yaml.safe_load(p.read_text()) or {}


def list_instances() -> list[InstanceContext]:
    out: list[InstanceContext] = []
    if not INSTANCES_DIR.exists():
        return out
    for d in sorted(INSTANCES_DIR.iterdir()):
        f = d / "instance.yaml"
        if d.name.startswith("_") or not f.exists():
            continue
        meta = yaml.safe_load(f.read_text()) or {}
        out.append(InstanceContext(id=meta.get("id", d.name), root=d, meta=meta))
    return out


def get_instance(instance_id: str) -> InstanceContext:
    for inst in list_instances():
        if inst.id == instance_id:
            return inst
    raise KeyError(f"unknown instance: {instance_id}")
