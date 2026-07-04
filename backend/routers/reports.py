from fastapi import APIRouter

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/")
async def list_reports() -> dict[str, str]:
    return {"message": "Reports router ready"}
