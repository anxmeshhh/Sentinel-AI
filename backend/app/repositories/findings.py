import uuid

from app.models.finding import Finding
from app.repositories.base import WorkspaceScopedRepository


class FindingRepository(WorkspaceScopedRepository[Finding]):
    model = Finding

    def for_run(self, run_id: uuid.UUID) -> list[Finding]:
        rows = self._scoped().where(Finding.run_id == run_id)
        return list(self.session.execute(rows).scalars().all())
