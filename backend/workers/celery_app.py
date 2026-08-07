from celery import Celery

try:
    from core.config import get_settings
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gl_reporting",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.report_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_time_limit=300,
    task_max_retries=3,
)
