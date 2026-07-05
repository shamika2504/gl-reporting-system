from celery import Celery

celery_app = Celery(
    "gl_reporting",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
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
