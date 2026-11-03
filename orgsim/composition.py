"""Composition root: bind domain ports to adapters here, never in a kernel."""
from .adapters.instances import InstanceModel, InstancePresenter, InstanceScorer, LocalRunRepository
from .application.simulation import SimulationService
from .instances import InstanceContext


def instance_service(ctx: InstanceContext) -> SimulationService:
    return SimulationService(InstanceModel(ctx), LocalRunRepository(ctx), InstanceScorer(ctx), InstancePresenter(ctx))
