"""Regression checks for defects found while integrating the new instances."""
import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def test_competing_exits_conserve_expected_population_independently_of_order():
    from orgsim.worlds.workforce import World

    def step(order):
        world = World.__new__(World)
        world.n = 1
        world.last_step = date(2025, 1, 1)
        world.offers = []
        world.dyn = {"hazards": {k: {"weekly": p} for k, p in order}}
        world.ns = SimpleNamespace(eval=lambda expr, _: np.array([float(expr)]))
        world.stock = "depleting"
        world.alive = np.array([10_000_000.0])
        world.expected_alive = world.alive.copy()
        world.expected_quits = np.zeros(1)
        world.rng = np.random.default_rng(41)
        world.decisions = {"quit": 0}
        world.quit_week = np.array([-1])
        world.week = 1
        expected, realized = {}, {}
        world._count = lambda name, days, e, r: (expected.update({name: e[0]}), realized.update({name: r[0]}))
        world._aggregate_rows = lambda *args: None
        world._cohort_step(date(2025, 1, 8), {}, datetime(2025, 1, 8))
        assert world.expected_alive[0] + sum(expected.values()) == pytest.approx(10_000_000)
        assert sum(expected.values()) == pytest.approx(3_600_000)
        assert abs(sum(realized.values()) - sum(expected.values())) < 10_000
        return expected

    assert step([("quit", ".2"), ("retire", ".2")]) == step([("retire", ".2"), ("quit", ".2")])


def test_board_uses_all_methods_and_only_common_cutoffs():
    path = Path(__file__).resolve().parents[1] / "board/score_openrouter.py"
    spec = importlib.util.spec_from_file_location("board_scores", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [{"combined": 99., "trend": 100.}, {"combined": 2., "trend": 4., "llm": 1.}]
    result = module.aggregate_methods(rows, "combined", "best_other")
    assert result["llm"] == 1.
    assert result["combined"] == 2.
    assert result["best_other"] == "llm"
    assert result["n_forecasts"] == 1
    assert result["method_counts"] == {"combined": 2, "trend": 2, "llm": 1}
    json.dumps(result)  # output must be serializable for the publisher
    assert module.aggregate_methods([{"combined": 1.}, {"trend": 2.}], "combined", "best_other") == {}
