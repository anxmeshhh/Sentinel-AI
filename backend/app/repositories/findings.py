import uuid

from app.models.finding import AgentFinding
from app.repositories.base import WorkspaceScopedRepository


class AgentFindingRepository(WorkspaceScopedRepository[AgentFinding]):
    model = AgentFinding

    def for_run(self, run_id: uuid.UUID) -> list[AgentFinding]:
        rows = self._scoped().where(AgentFinding.run_id == run_id)
        return list(self.session.execute(rows).scalars().all())
