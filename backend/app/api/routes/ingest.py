from fastapi import APIRouter

router = APIRouter(prefix="/ingest", tags=["Ingest & Reconcile"])


@router.get("/")
def get_ingest_status():
    return {"module": "ingest", "status": "ok"}
