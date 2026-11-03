"""Use cases shared by CLI, HTTP results, and alternative-action execution."""
from dataclasses import dataclass

from .ports import OutcomeScorer, ResultsPresenter, RunRepository, SimulationModel


@dataclass(frozen=True)
class CompletedRun:
    run_id: str
    n_events: int
    summary: dict


@dataclass
class SimulationService:
    model: SimulationModel
    runs: RunRepository
    scorer: OutcomeScorer
    presenter: ResultsPresenter

    def run(self, scenario: dict, seed: int, *, metadata: dict | None = None) -> CompletedRun:
        sink = self.runs.begin(scenario, seed, metadata or {})
        try:
            summary = self.model.run(scenario, seed, sink)
            sink.close(summary)
        except BaseException:
            sink.abort()
            raise
        return CompletedRun(sink.run_id, sink.n_events, summary)

    def evaluate(self, scenario_ids: list[str]) -> dict:
        return self.scorer.evaluate(scenario_ids)

    def results(self) -> dict:
        return self.presenter.present()
