from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "sentinel",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # a crashed worker mid-task doesn't lose the task
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.workers.tasks.ingest_connection": {"queue": "ingestion"},
        "app.workers.tasks.run_agents_for_connection": {"queue": "agents"},
    },
)

celery_app.conf.beat_schedule = {
    "poll-all-connections": {
        "task": "app.workers.tasks.poll_all_connections",
        "schedule": _settings.ingestion_poll_interval_seconds,
    },
}
