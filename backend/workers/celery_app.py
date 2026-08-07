from celery import Celery
from celery.signals import worker_init

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


@worker_init.connect
def _start_metrics_server(**kwargs):
    # worker_init only fires when an actual `celery worker` process boots —
    # not when this module is merely imported (e.g. by the backend to call
    # generate_report_task.delay()) — so the metrics server never tries to
    # start inside the FastAPI pods, only the real worker.
    from prometheus_client import start_http_server

    start_http_server(9100)
