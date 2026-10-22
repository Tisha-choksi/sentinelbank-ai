from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from api.alerts import router as alerts_router
from db import Base, engine, get_db
from detection import service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prototype setup: create tables that do not exist yet.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="SentinelBank AI",
    description="Banking fraud investigation platform",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(alerts_router)

DbSession = Annotated[Session, Depends(get_db)]


class TransactionCreate(BaseModel):
    transaction_ref: str = Field(min_length=1, max_length=64)
    from_account: str = Field(min_length=1, max_length=64)
    to_account: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")


class TransactionResponse(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime


@app.get("/")
def home():
    return {
        "project": "SentinelBank AI",
        "message": "Banking risk intelligence platform is running",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/database")
def health_database(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "status": "connected",
        "database": "sentinelbank",
    }


@app.post(
    "/api/v1/transactions",
    response_model=TransactionResponse,
    status_code=201,
)
def create_transaction(payload: TransactionCreate, db: DbSession):
    transaction = models.Transaction(**payload.model_dump())
    db.add(transaction)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Transaction '{payload.transaction_ref}' already exists",
        ) from exc
    db.refresh(transaction)
    service.run_detection(db, transaction)
    return transaction


@app.get("/api/v1/transactions", response_model=list[TransactionResponse])
def list_transactions(db: DbSession):
    result = db.execute(select(models.Transaction).order_by(models.Transaction.id))
    return result.scalars().all()
