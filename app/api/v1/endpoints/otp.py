import hashlib
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import OTPCode, OTPMethod, OTPStatus
from app.services.sms_provider import send_otp_code

logger = logging.getLogger(__name__)
router = APIRouter()

API_KEY = os.getenv("API_KEY", "change_me")
OTP_LENGTH = int(os.getenv("OTP_LENGTH", "4"))
OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "5"))
MAX_VERIFY_ATTEMPTS = int(os.getenv("MAX_VERIFY_ATTEMPTS", "3"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "3"))

# phone -> список timestamp'ов последних запросов на отправку (in-memory, один процесс)
_send_attempts: dict[str, list[float]] = {}


class SendOTPRequest(BaseModel):
    phone: str
    method: str = "sms"


class SendOTPResponse(BaseModel):
    request_id: str
    status: str
    masked_phone: str
    expires_in_seconds: int
    dev_code: str | None = None


class VerifyOTPRequest(BaseModel):
    request_id: str
    code: str
    phone: str


class VerifyOTPResponse(BaseModel):
    valid: bool
    message: str


def verify_api_key(authorization: str = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="API key required")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def mask_phone(phone: str) -> str:
    if len(phone) >= 10:
        return f"{phone[:2]} ({phone[2:5]}) {phone[5:8]}-**-**"
    return phone


def check_rate_limit(phone: str) -> None:
    now = time.time()
    attempts = [t for t in _send_attempts.get(phone, []) if now - t < 60]
    if len(attempts) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests, try again later")
    attempts.append(now)
    _send_attempts[phone] = attempts


@router.post("/send", response_model=SendOTPResponse)
async def send_otp(
    request: SendOTPRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    if request.method not in (OTPMethod.sms.value, OTPMethod.flash_call.value):
        raise HTTPException(status_code=400, detail="Invalid method")

    check_rate_limit(request.phone)

    code = "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))
    phone_hash = hash_value(request.phone)
    code_hash = hash_value(code + request.phone)

    otp_record = OTPCode(
        id=str(uuid.uuid4()),
        phone_hash=phone_hash,
        code_hash=code_hash,
        method=OTPMethod(request.method),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    db.add(otp_record)
    db.commit()

    success = await send_otp_code(request.phone, code, request.method)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to send OTP")

    logger.info("OTP отправлен на %s, request_id=%s", mask_phone(request.phone), otp_record.id)

    # Код в открытом виде отдаём в ответе ТОЛЬКО в mock-режиме (нет реальной
    # отправки, иначе взять код неоткуда, кроме лога) — для smoke-тестов и
    # локальной разработки. В live-режиме поле всегда None.
    dev_code = code if os.getenv("SMS_MODE", "mock") == "mock" else None

    return SendOTPResponse(
        request_id=otp_record.id,
        status="sent",
        masked_phone=mask_phone(request.phone),
        expires_in_seconds=OTP_TTL_MINUTES * 60,
        dev_code=dev_code,
    )


@router.post("/verify", response_model=VerifyOTPResponse)
async def verify_otp(
    request: VerifyOTPRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    otp_record = db.query(OTPCode).filter(OTPCode.id == request.request_id).first()

    if not otp_record:
        raise HTTPException(status_code=404, detail="Request not found")

    if otp_record.status != OTPStatus.pending:
        raise HTTPException(status_code=400, detail=f"Code already {otp_record.status.value}")

    if datetime.utcnow() > otp_record.expires_at:
        otp_record.status = OTPStatus.expired
        db.commit()
        raise HTTPException(status_code=400, detail="Code expired")

    if otp_record.attempts >= MAX_VERIFY_ATTEMPTS:
        otp_record.status = OTPStatus.max_attempts
        db.commit()
        raise HTTPException(status_code=400, detail="Max attempts exceeded")

    code_hash = hash_value(request.code + request.phone)

    if code_hash == otp_record.code_hash:
        otp_record.status = OTPStatus.verified
        db.commit()
        logger.info("Код подтверждён для %s", mask_phone(request.phone))
        return VerifyOTPResponse(valid=True, message="Code verified successfully")

    otp_record.attempts += 1
    db.commit()
    logger.warning("Неверный код для %s, попытка %s", mask_phone(request.phone), otp_record.attempts)
    return VerifyOTPResponse(valid=False, message="Invalid code")
