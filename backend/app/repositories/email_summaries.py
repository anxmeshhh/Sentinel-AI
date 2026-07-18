from app.models.email_summary import EmailSummary
from app.repositories.base import WorkspaceScopedRepository


class EmailSummaryRepository(WorkspaceScopedRepository[EmailSummary]):
    model = EmailSummary

    def get_by_message_id(self, message_id: str) -> EmailSummary | None:
        return self.session.execute(self._scoped().where(EmailSummary.message_id == message_id)).scalar_one_or_none()
