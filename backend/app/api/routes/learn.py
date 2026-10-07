from fastapi import APIRouter

router = APIRouter(prefix="/learn", tags=["Execute & Learn"])


@router.get("/")
def get_learn_status():
    return {"module": "learn", "status": "ok"}
