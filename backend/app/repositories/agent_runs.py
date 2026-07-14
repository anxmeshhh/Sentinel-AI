from datetime import datetime, timezone

from sqlalchemy import desc

from app.models.agent_run import AgentRun, RunStatus, TriggeredBy
from app.repositories.base import WorkspaceScopedRepository


class AgentRunRepository(WorkspaceScopedRepository[AgentRun]):
    model = AgentRun

    def list_recent(self, limit: int = 50) -> list[AgentRun]:
        rows = self._scoped().order_by(desc(AgentRun.started_at)).limit(limit)
        return list(self.session.execute(rows).scalars().all())

    def start(self, *, connection_id, triggered_by: TriggeredBy) -> AgentRun:
        run = AgentRun(
            connection_id=connection_id,
            status=RunStatus.RUNNING,
            triggered_by=triggered_by,
            started_at=datetime.now(timezone.utc),
        )
        self.add(run)
        self.session.flush()  # assign run.id without committing, so callers can use it immediately
        return run

    def finish(self, run: AgentRun, *, status: RunStatus, node_errors: dict | None = None, error: str | None = None) -> None:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.node_errors = node_errors or {}
        run.error = error
        self.session.add(run)
