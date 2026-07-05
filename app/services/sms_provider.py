import logging
import os

import httpx

logger = logging.getLogger(__name__)


class BaseSMSProvider:
    async def send(self, phone: str, code: str, method: str) -> bool:
        raise NotImplementedError


class MockProvider(BaseSMSProvider):
    """Ничего никуда не отправляет, печатает код в лог. Для разработки/демо."""

    async def send(self, phone: str, code: str, method: str) -> bool:
        logger.info("=" * 50)
        logger.info("MOCK %s -> %s", method.upper(), phone)
        logger.info("CODE: %s", code)
        logger.info("=" * 50)
        return True


class SMSCProvider(BaseSMSProvider):
    """SMSC.ru — SMS и flash-call (звонок, код = последние цифры номера)."""

    def __init__(self):
        self.login = os.getenv("SMSC_LOGIN", "")
        self.password = os.getenv("SMSC_PASSWORD", "")
        self.sender = os.getenv("SMSC_SENDER_ID", "")

    async def send(self, phone: str, code: str, method: str) -> bool:
        phone_clean = phone.lstrip("+")
        url = "https://smsc.ru/sys/send.php"

        if method == "flash_call":
            params = {
                "login": self.login,
                "psw": self.password,
                "phones": phone_clean,
                "call": 1,
                "fmt": 3,
            }
        else:
            params = {
                "login": self.login,
                "psw": self.password,
                "phones": phone_clean,
                "mes": f"Код подтверждения: {code}",
                "sender": self.sender,
                "fmt": 3,
            }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, data=params)
                data = response.json()
                if "error" in data:
                    logger.error("SMSC error: %s", data)
                    return False
                logger.info("SMSC: %s отправлен на %s", method, phone)
                return True
        except Exception:
            logger.exception("SMSC request failed")
            return False


class SMSRuProvider(BaseSMSProvider):
    """SMS.ru — резервный канал (только SMS, без flash-call)."""

    def __init__(self):
        self.api_id = os.getenv("SMSRU_API_ID", "")

    async def send(self, phone: str, code: str, method: str) -> bool:
        phone_clean = phone.lstrip("+")
        url = "https://sms.ru/sms/send"
        params = {
            "api_id": self.api_id,
            "to": phone_clean,
            "msg": f"Код подтверждения: {code}",
            "json": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params)
                data = response.json()
                if data.get("status") != "OK":
                    logger.error("SMS.ru error: %s", data)
                    return False
                logger.info("SMS.ru: SMS отправлен на %s", phone)
                return True
        except Exception:
            logger.exception("SMS.ru request failed")
            return False


async def send_otp_code(phone: str, code: str, method: str) -> bool:
    """Отправляет код через основной канал, при сбое — через резервный (только для SMS)."""
    mode = os.getenv("SMS_MODE", "mock")

    if mode == "mock":
        return await MockProvider().send(phone, code, method)

    if await SMSCProvider().send(phone, code, method):
        return True

    if method == "sms":
        logger.warning("SMSC недоступен, пробуем SMS.ru")
        return await SMSRuProvider().send(phone, code, method)

    return False
