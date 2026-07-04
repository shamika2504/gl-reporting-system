from fastapi import APIRouter

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/")
async def monitoring_status() -> dict[str, str]:
    return {"message": "Monitoring router ready"}
