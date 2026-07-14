from sqlalchemy import desc

from app.models.brief import Brief
from app.repositories.base import WorkspaceScopedRepository


class BriefRepository(WorkspaceScopedRepository[Brief]):
    model = Brief

    def latest(self) -> Brief | None:
        rows = self._scoped().order_by(desc(Brief.generated_at)).limit(1)
        return self.session.execute(rows).scalar_one_or_none()

    def history(self, limit: int = 30) -> list[Brief]:
        rows = self._scoped().order_by(desc(Brief.generated_at)).limit(limit)
        return list(self.session.execute(rows).scalars().all())
