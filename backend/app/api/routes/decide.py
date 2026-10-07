from fastapi import APIRouter

router = APIRouter(prefix="/decide", tags=["Decide"])


@router.get("/")
def get_decide_status():
    return {"module": "decide", "status": "ok"}
