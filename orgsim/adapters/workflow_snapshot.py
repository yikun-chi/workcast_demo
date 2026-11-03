"""Typed, cutoff-filtered task snapshots from authored or normalized records."""
from dataclasses import dataclass
from datetime import datetime

from ..workflow.contracts import Observation, WorkflowSpec


@dataclass(frozen=True)
class RecordSnapshot:
    spec: WorkflowSpec

    def read(self, as_of: datetime) -> Observation:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Snapshot cutoff must include a timezone")
        # Effective time and publication/availability time are distinct gates.
        versions = {}
        for record in self.spec.records:
            if record.effective_at > as_of or record.available_at > as_of:
                continue
            old = versions.get(record.task.id)
            rank = (record.available_at, record.effective_at)
            if old is not None and rank == (old.available_at, old.effective_at) and record != old:
                raise ValueError("Conflicting task versions with identical timestamps")
            if old is None or rank > (old.available_at, old.effective_at):
                versions[record.task.id] = record
        visible = [r.task for r in versions.values()]
        return Observation(as_of=as_of, tasks=tuple(sorted(visible, key=lambda t: t.id)),
                           resources=tuple(sorted(self.spec.resources, key=lambda r: r.id)), horizon_h=self.spec.horizon_h)
