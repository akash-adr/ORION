from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import ingest, diagnose, decide, learn

app = FastAPI(
    title="Next-Generation Autonomous D2C Advertising Intelligence & Decision Engine",
    version="0.1.0",
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check route
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Register module routers
app.include_router(ingest.router)
app.include_router(diagnose.router)
app.include_router(decide.router)
app.include_router(learn.router)
