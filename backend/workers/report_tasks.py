from workers.celery_app import celery_app


@celery_app.task(name="generate_report")
def generate_report(period_id: int) -> dict[str, object]:
    return {"status": "queued", "period_id": period_id}
