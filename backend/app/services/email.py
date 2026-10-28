"""SMTP 이메일 발송. SMTP_HOST/SMTP_FROM 이 없으면 '미연동' 상태입니다."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import aiosmtplib

from app.config import Settings


class EmailNotConfiguredError(Exception):
    pass


class EmailSendError(Exception):
    pass


def _header_safe(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:200]


class EmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.smtp_configured

    async def send(self, to: str, subject: str, body: str) -> None:
        s = self.settings
        if not self.configured:
            raise EmailNotConfiguredError("SMTP 가 설정되지 않았습니다 (미연동).")
        message = EmailMessage()
        message["From"] = s.smtp_from
        message["To"] = _header_safe(to)
        message["Subject"] = _header_safe(subject)
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=(s.smtp_from or "uptimewatch").split("@")[-1].strip(">"))
        message.set_content(body)
        try:
            await aiosmtplib.send(
                message,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_username or None,
                password=s.smtp_password.get_secret_value() if s.smtp_password else None,
                start_tls=s.smtp_starttls and not s.smtp_ssl,
                use_tls=s.smtp_ssl,
                timeout=s.smtp_timeout_seconds,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            # 비밀번호 등 민감정보가 섞이지 않도록 예외 종류와 요약만 남깁니다.
            raise EmailSendError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc
