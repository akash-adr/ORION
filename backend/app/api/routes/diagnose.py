from fastapi import APIRouter

router = APIRouter(prefix="/diagnose", tags=["Diagnose & Reason"])


@router.get("/")
def get_diagnose_status():
    return {"module": "diagnose", "status": "ok"}
