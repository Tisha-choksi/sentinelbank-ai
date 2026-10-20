from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(
    title="SentinelBank AI",
    description="AI-powered banking fraud investigation platform",
    version="0.1.0",
)


@app.get("/")
def home():
    return {
        "project": "SentinelBank AI",
        "message": "Banking risk intelligence platform is running",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
