"""Contract and behavioral checks shared by every task-planner implementation."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from orgsim.adapters.decision_store import SQLiteDecisionRepository
from orgsim.adapters.planners import load_planner
from orgsim.adapters.rule_planner import RulePlanner, assign_task
from orgsim.adapters.workflow_snapshot import RecordSnapshot
from orgsim.application.workflow import WorkflowService, replay
from orgsim.workflow.contracts import Observation, WorkflowSpec
from orgsim.workflow.kernel import simulate, validate_plan


@pytest.fixture
def spec():
    path = Path(__file__).resolve().parents[1] / "examples/task_workflow.json"
    return WorkflowSpec.model_validate_json(path.read_text())


@pytest.fixture
def observation(spec):
    return RecordSnapshot(spec).read(spec.as_of)


def test_snapshots_gate_effective_and_availability_dates(spec):
    original = spec.records[0]
    late_publication = original.model_copy(update={"available_at": spec.as_of + timedelta(days=1)})
    future_effective = original.model_copy(update={"effective_at": spec.as_of + timedelta(days=1)})
    for record in (late_publication, future_effective):
        snapshot = RecordSnapshot(spec.model_copy(update={"records": (record,)}))
        assert snapshot.read(spec.as_of).tasks == ()
    data = original.model_dump(mode="json")
    del data["available_at"]
    with pytest.raises(ValueError):
        type(original).model_validate(data)
    with pytest.raises(ValueError):
        RecordSnapshot(spec).read(spec.as_of.replace(tzinfo=None))
    # Truth cannot be smuggled into the typed input envelope.
    data = spec.model_dump(mode="json")
    data["actual_outcomes"] = {"completed_tasks": 200}
    with pytest.raises(ValueError):
        WorkflowSpec.model_validate(data)


def test_no_future_truth_in_planner_input(spec, tmp_path):
    seen = []
    class Spy(RulePlanner):
        def plan(self, obs):
            seen.append(obs.model_dump(mode="json"))
            return super().plan(obs)
    service = WorkflowService(RecordSnapshot(spec), Spy(), SQLiteDecisionRepository(tmp_path / "journal.sqlite"))
    service.run(spec.as_of, spec.seed)
    assert set(seen[0]) == {"as_of", "tasks", "resources", "horizon_h"}
    assert "seed" not in seen[0] and "result" not in seen[0]


def test_snapshot_selects_available_vintage_and_rejects_ambiguous_revisions(spec):
    old = spec.records[0]
    revision = old.model_copy(update={"available_at": spec.as_of + timedelta(days=1),
                                      "task": old.task.model_copy(update={"work_h": 100})})
    snapshot = RecordSnapshot(spec.model_copy(update={"records": (old, revision)}))
    assert snapshot.read(spec.as_of).tasks[0].work_h == old.task.work_h
    assert snapshot.read(revision.available_at).tasks[0].work_h == 100
    ambiguous = revision.model_copy(update={"available_at": old.available_at})
    with pytest.raises(ValueError, match="Conflicting"):
        RecordSnapshot(spec.model_copy(update={"records": (old, ambiguous)})).read(spec.as_of)


def test_invalid_dependencies_and_nonfinite_parameters_fail(observation):
    task = observation.tasks[0]
    for dependencies in ((task.id,), ("missing",)):
        with pytest.raises(ValueError):
            Observation(**{**observation.model_dump(), "tasks": [task.model_copy(update={"depends_on": dependencies})]})
    for value in (float("nan"), float("inf"), -1):
        data = task.model_dump()
        data["work_h"] = value
        with pytest.raises(ValueError):
            type(task).model_validate(data)


def test_commands_are_idempotent_and_batch_validation_is_atomic(observation):
    plan = RulePlanner().plan(observation)
    duplicate = plan.model_copy(update={"proposals": plan.proposals + (plan.proposals[0],)})
    assert simulate(observation, duplicate, 7) == simulate(observation, plan, 7)
    conflicting = plan.proposals[0].model_copy(update={"assignee_id": "analyst"})
    with pytest.raises(ValueError, match="Conflicting"):
        validate_plan(observation, plan.model_copy(update={"proposals": plan.proposals + (conflicting,)}))
    for update in ({"assignee_id": "unknown"}, {"reviewer_id": "assistant"}, {"command_id": "stale"}):
        invalid = plan.proposals[0].model_copy(update=update)
        with pytest.raises(ValueError):
            validate_plan(observation, plan.model_copy(update={"proposals": (invalid, *plan.proposals[1:])}))
    with pytest.raises(ValueError, match="every visible task"):
        validate_plan(observation, plan.model_copy(update={"proposals": plan.proposals[:-1]}))


def test_capacity_dependencies_review_and_order_invariance(observation):
    plan = RulePlanner().plan(observation)
    result = simulate(observation, plan, 17)
    reverse = plan.model_copy(update={"proposals": tuple(reversed(plan.proposals))})
    assert simulate(observation, reverse, 17) == result
    events = result["events"]
    for resource in observation.resources:
        for slot in range(resource.capacity):
            allocated = [e for e in events if e["resource_id"] == resource.id and e["slot"] == slot]
            assert all(a["end_h"] <= b["start_h"] for a, b in zip(allocated, allocated[1:]))
    for task in observation.tasks:
        stages = [e for e in events if e["task_id"] == task.id]
        work = next(e for e in stages if e["stage"] == "work")
        review = next(e for e in stages if e["stage"] == "review")
        assert work["end_h"] <= review["start_h"]
        for dep in task.depends_on:
            assert max(e["end_h"] for e in events if e["task_id"] == dep) <= work["start_h"]
    assert result["outcomes"]["completed_tasks"] == 3


def test_horizon_charges_only_performed_effort_and_service(observation):
    data = observation.model_dump()
    data["tasks"] = [observation.tasks[0].model_dump()]
    data["horizon_h"] = 0.5
    short = Observation.model_validate(data)
    outcome = simulate(short, RulePlanner().plan(short), 1)["outcomes"]
    assert outcome == {"completed_tasks": 0, "throughput_per_hour": 0, "mean_elapsed_h": None,
                       "staff_effort_h": 0, "correction_rate": None, "service_cost": pytest.approx(.1)}


def test_review_and_correction_are_paid_human_work(observation):
    task = observation.tasks[0].model_copy(update={"error_probability": 1.0})
    obs = Observation(**{**observation.model_dump(), "tasks": [task]})
    outcome = simulate(obs, RulePlanner().plan(obs), 1)["outcomes"]
    assert outcome["staff_effort_h"] == task.review_h + task.rework_h
    assert outcome["correction_rate"] == 1
    assert outcome["mean_elapsed_h"] == task.work_h / 3 + task.review_h + task.rework_h


def test_restart_after_decision_commit_never_replans(spec, tmp_path, monkeypatch):
    from orgsim.application import workflow
    journal = SQLiteDecisionRepository(tmp_path / "journal.sqlite")
    calls = []
    class Count(RulePlanner):
        def plan(self, obs):
            calls.append(1)
            return super().plan(obs)
    service = WorkflowService(RecordSnapshot(spec), Count(), journal)
    def crash(*args):
        raise RuntimeError("interrupted after planning")
    monkeypatch.setattr(workflow, "simulate", crash)
    with pytest.raises(RuntimeError):
        service.run(spec.as_of, spec.seed)
    monkeypatch.setattr(workflow, "simulate", simulate)
    restarted = WorkflowService(RecordSnapshot(spec), Count(), SQLiteDecisionRepository(journal.path))
    result = restarted.run(spec.as_of, spec.seed)
    assert restarted.run(spec.as_of, spec.seed) == result
    assert calls == [1]
    assert replay(journal, result["run_key"]) == result
    # A different process replays with only saved JSON + the kernel.
    code = "from pathlib import Path; from orgsim.adapters.decision_store import SQLiteDecisionRepository; from orgsim.application.workflow import replay; import sys; replay(SQLiteDecisionRepository(Path(sys.argv[1])), sys.argv[2])"
    subprocess.run([sys.executable, "-c", code, str(journal.path), result["run_key"]], check=True)


def test_journal_rejects_conflicting_writes_and_input_changes_replan(spec, tmp_path):
    journal = SQLiteDecisionRepository(tmp_path / "journal.sqlite")
    journal.write_once("test", "key", {"value": 1})
    journal.write_once("test", "key", {"value": 1})
    with pytest.raises(ValueError, match="Conflicting"):
        journal.write_once("test", "key", {"value": 2})
    original = WorkflowService(RecordSnapshot(spec), RulePlanner(), journal).run(spec.as_of, 1)
    changed = spec.model_copy(update={"horizon_h": 1})
    other = WorkflowService(RecordSnapshot(changed), RulePlanner(), journal).run(changed.as_of, 1)
    assert original["decision_key"] != other["decision_key"]


def test_an_external_framework_adapter_needs_no_kernel_changes(observation, tmp_path, monkeypatch):
    external = ModuleType("example_framework")
    # A minimal stand-in for a separately installed Microsoft/custom adapter.
    external.create = lambda checkpoint_dir, **options: RulePlanner()
    monkeypatch.setitem(sys.modules, external.__name__, external)
    planner = load_planner("example_framework:create", tmp_path)
    assert simulate(observation, planner.plan(observation), 1) == simulate(observation, RulePlanner().plan(observation), 1)


def test_base_runtime_does_not_import_optional_framework():
    subprocess.run([sys.executable, "-c", "import sys; import orgsim.cli; from orgsim.adapters.planners import load_planner; from pathlib import Path; load_planner('rule', Path('.')); assert not any(k.startswith(('langgraph', 'langchain', 'agent_framework')) for k in sys.modules)"], check=True)


def test_langgraph_matches_rule_despite_worker_order_and_restarts(observation, tmp_path):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    from orgsim.adapters.langgraph_planner import LangGraphPlanner
    import time
    calls = []
    def worker(obs, task):
        time.sleep(.02 if task.id == "invoice-a" else .001)
        calls.append(task.id)
        return assign_task(obs, task)
    planner = LangGraphPlanner(tmp_path / "graph.sqlite", worker=worker, worker_version="test-fixture", max_concurrency=3)
    plan = planner.plan(observation)
    assert len(calls) == len(observation.tasks)
    assert simulate(observation, plan, 17) == simulate(observation, RulePlanner().plan(observation), 17)
    resumed = LangGraphPlanner(tmp_path / "graph.sqlite", worker=worker, worker_version="test-fixture", max_concurrency=1)
    assert resumed.plan(observation) == plan
    assert len(calls) == len(observation.tasks)
    serial = LangGraphPlanner(tmp_path / "serial.sqlite", max_concurrency=1).plan(observation)
    assert simulate(observation, serial, 17) == simulate(observation, plan, 17)


def test_langgraph_resumes_failed_worker_from_persistent_checkpoint(observation, tmp_path):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    from orgsim.adapters.langgraph_planner import LangGraphPlanner
    calls = []
    fail = True
    def worker(obs, task):
        calls.append(task.id)
        if task.id == "invoice-b" and fail:
            raise RuntimeError("worker interrupted")
        return assign_task(obs, task)
    planner = LangGraphPlanner(tmp_path / "graph.sqlite", worker=worker, worker_version="recovery-fixture", max_concurrency=1)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        planner.plan(observation)
    fail = False
    plan = LangGraphPlanner(tmp_path / "graph.sqlite", worker=worker, worker_version="recovery-fixture", max_concurrency=1).plan(observation)
    assert calls.count("invoice-a") == 1  # successful worker was checkpointed
    assert calls.count("invoice-b") == 2
    assert simulate(observation, plan, 1) == simulate(observation, RulePlanner().plan(observation), 1)


def test_empty_graph_is_a_valid_no_work_plan(observation, tmp_path):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    from orgsim.adapters.langgraph_planner import LangGraphPlanner
    empty = observation.model_copy(update={"tasks": ()})
    plan = LangGraphPlanner(tmp_path / "empty.sqlite").plan(empty)
    assert simulate(empty, plan, 1)["outcomes"]["completed_tasks"] == 0
