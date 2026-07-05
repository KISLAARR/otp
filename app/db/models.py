import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Enum

from app.db.database import Base


class OTPMethod(str, enum.Enum):
    sms = "sms"
    flash_call = "flash_call"


class OTPStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    expired = "expired"
    max_attempts = "max_attempts"


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone_hash = Column(String(64), index=True, nullable=False)
    code_hash = Column(String(64), nullable=False)
    method = Column(Enum(OTPMethod), nullable=False)
    status = Column(Enum(OTPStatus), nullable=False, default=OTPStatus.pending)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
