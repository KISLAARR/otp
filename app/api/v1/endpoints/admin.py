from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.endpoints.otp import verify_api_key
from app.db.database import get_db
from app.db.models import OTPCode, OTPStatus

router = APIRouter()

_start_time = datetime.utcnow()


@router.get("/status")
async def status():
    uptime = datetime.utcnow() - _start_time
    return {
        "service": "OTP Service",
        "version": "1.0.0",
        "status": "healthy",
        "uptime_seconds": int(uptime.total_seconds()),
        "started_at": _start_time.isoformat(),
    }


@router.get("/stats")
async def stats(db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)):
    total_sent = db.query(OTPCode).count()
    total_verified = db.query(OTPCode).filter(OTPCode.status == OTPStatus.verified).count()
    active_codes = (
        db.query(OTPCode)
        .filter(OTPCode.status == OTPStatus.pending, OTPCode.expires_at > datetime.utcnow())
        .count()
    )
    return {
        "total_sent": total_sent,
        "total_verified": total_verified,
        "active_codes": active_codes,
    }
