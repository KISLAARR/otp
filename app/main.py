import logging

from fastapi import FastAPI

from app.api.v1.endpoints import otp, admin
from app.db.database import Base, engine
from app.db import models  # noqa: F401 — регистрирует модели в Base.metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(title="OTP Service", version="1.0.0")

app.include_router(otp.router, prefix="/api/v1/otp", tags=["OTP"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
