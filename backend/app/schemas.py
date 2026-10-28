from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.services.status_codes import StatusSpecError, normalize_status_spec

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 인증 ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=100)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: int
    email: str
    display_name: str
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    csrf_token: str


# ---------- 모니터 ----------
class MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    method: Literal["GET", "HEAD"] = "GET"
    interval_seconds: int = Field(default=300)
    timeout_seconds: int = Field(default=10)
    expected_status: str = Field(default="200-299", max_length=100)
    failure_threshold: int = Field(default=3, ge=1, le=10)
    recovery_threshold: int = Field(default=1, ge=1, le=10)
    follow_redirects: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력하세요.")
        return v

    @field_validator("expected_status")
    @classmethod
    def _status(cls, v: str) -> str:
        try:
            return normalize_status_spec(v)
        except StatusSpecError as exc:
            raise ValueError(str(exc)) from exc


class MonitorCreate(MonitorBase):
    is_active: bool = True


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    method: Literal["GET", "HEAD"] | None = None
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    expected_status: str | None = Field(default=None, max_length=100)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    recovery_threshold: int | None = Field(default=None, ge=1, le=10)
    follow_redirects: bool | None = None

    @field_validator("expected_status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            return normalize_status_spec(v)
        except StatusSpecError as exc:
            raise ValueError(str(exc)) from exc


class MonitorOut(ORMModel):
    id: int
    name: str
    description: str
    url: str
    method: str
    interval_seconds: int
    timeout_seconds: int
    expected_status: str
    failure_threshold: int
    recovery_threshold: int
    follow_redirects: bool
    is_active: bool
    status: str
    status_changed_at: datetime | None
    consecutive_failures: int
    consecutive_successes: int
    last_checked_at: datetime | None
    last_outcome: str | None
    last_status_code: int | None
    last_response_time_ms: int | None
    last_error_type: str | None
    last_error_message: str | None
    next_check_at: datetime | None
    manual_check_requested_at: datetime | None
    tls_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MonitorListItem(MonitorOut):
    uptime_24h: float | None = None
    avg_response_24h: float | None = None
    open_incident_id: int | None = None


class CheckOut(ORMModel):
    id: int
    checked_at: datetime
    outcome: str
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None
    redirect_count: int
    is_manual: bool


class IncidentOut(BaseModel):
    id: int
    monitor_id: int
    monitor_name: str
    started_at: datetime
    detected_at: datetime
    resolved_at: datetime | None
    duration_seconds: int | None
    ongoing_seconds: int | None
    cause_type: str | None
    cause_message: str | None
    failed_checks: int


# ---------- 알림 ----------
class NotificationOut(ORMModel):
    id: int
    monitor_id: int | None
    incident_id: int | None
    kind: str
    title: str
    message: str
    created_at: datetime
    read_at: datetime | None


class DeliveryOut(ORMModel):
    id: int
    notification_id: int
    monitor_id: int | None
    kind: str
    channel: str
    recipient: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class NotificationSettingsIn(BaseModel):
    email_enabled: bool = True
    email_to: EmailStr | None = None
    email_cooldown_minutes: int = Field(default=10, ge=0, le=1440)
    reminder_interval_minutes: int = Field(default=0, ge=0, le=1440)
    tls_warning_days: int = Field(default=14, ge=0, le=90)


class NotificationSettingsOut(NotificationSettingsIn):
    email_to: str | None = None


# ---------- 상태 페이지 ----------
class StatusPageItemIn(BaseModel):
    monitor_id: int
    display_name: str = Field(min_length=1, max_length=100)


class StatusPageIn(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    is_published: bool = False
    show_uptime: bool = True
    show_response_times: bool = False
    show_incidents: bool = True
    items: list[StatusPageItemIn] = Field(default_factory=list, max_length=100)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not SLUG_RE.match(v):
            raise ValueError("주소(slug)는 영문 소문자·숫자·하이픈 3~64자로 입력하세요.")
        return v


class StatusPageItemOut(BaseModel):
    monitor_id: int
    display_name: str
    sort_order: int


class StatusPageOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str
    is_published: bool
    show_uptime: bool
    show_response_times: bool
    show_incidents: bool
    items: list[StatusPageItemOut]
    created_at: datetime
    updated_at: datetime
