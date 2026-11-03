"""Authored workflow exploration, separate from registered-instance validation."""
import json
from pathlib import Path

from ..adapters.decision_store import SQLiteDecisionRepository
from ..adapters.planners import load_planner
from ..adapters.workflow_snapshot import RecordSnapshot
from ..application.workflow import WorkflowService, replay
from .contracts import WorkflowSpec


def run_cli(args) -> int:
    directory = Path(args.output)
    journal = SQLiteDecisionRepository(directory / "decisions.sqlite")
    if args.replay:
        print(json.dumps(replay(journal, args.replay), indent=2))
        return 0
    spec = WorkflowSpec.model_validate_json(Path(args.spec).read_text())
    planner = load_planner(args.planner, directory, json.loads(args.planner_options))
    result = WorkflowService(RecordSnapshot(spec), planner, journal).run(spec.as_of, spec.seed)
    document = {"track": "authored exploration; no observed outcomes or accuracy claim",
                "planner": planner.identity, **result}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result['run_key']}.json"
    path.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"artifact": str(path), **document}, indent=2))
    return 0
