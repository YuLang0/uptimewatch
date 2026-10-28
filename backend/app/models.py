"""데이터베이스 모델.

설계 원칙
- 모든 모니터링 데이터는 users.id 를 루트로 하는 소유 관계를 가지며, API 는 항상 user_id 로 필터링합니다.
- 검사 결과(check_results)는 원본 관측값이며 가동률/응답시간 통계는 여기서 계산합니다.
- 응답 본문·응답 헤더·임의 요청 헤더는 저장하지 않습니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _ts(nullable: bool = False, **kwargs) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, **kwargs)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class UserSession(Base):
    """서버 측 세션. 토큰 원문은 저장하지 않고 SHA-256 해시만 저장합니다."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    expires_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts(server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(200))


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # None 이면 계정 이메일로 발송
    email_to: Mapped[str | None] = mapped_column(String(254))
    # 같은 모니터·같은 종류의 이메일을 이 시간 안에 다시 보내지 않음
    email_cooldown_minutes: Mapped[int] = mapped_column(Integer, default=10)
    # 장애가 계속될 때 재알림 간격(0 = 재알림 안 함)
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, default=0)
    tls_warning_days: Mapped[int] = mapped_column(Integer, default=14)
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (Index("ix_monitors_due", "is_active", "next_check_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(2048))
    method: Mapped[str] = mapped_column(String(8), default="GET")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    expected_status: Mapped[str] = mapped_column(String(100), default="200-299")
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)
    recovery_threshold: Mapped[int] = mapped_column(Integer, default=1)
    follow_redirects: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 상태: pending(측정 전) | up | down | paused
    status: Mapped[str] = mapped_column(String(16), default="pending")
    status_changed_at: Mapped[datetime | None] = _ts(nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    failure_streak_started_at: Mapped[datetime | None] = _ts(nullable=True)
    success_streak_started_at: Mapped[datetime | None] = _ts(nullable=True)

    last_checked_at: Mapped[datetime | None] = _ts(nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(8))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_response_time_ms: Mapped[int | None] = mapped_column(Integer)
    last_error_type: Mapped[str | None] = mapped_column(String(32))
    last_error_message: Mapped[str | None] = mapped_column(String(500))

    next_check_at: Mapped[datetime | None] = _ts(nullable=True)
    manual_check_requested_at: Mapped[datetime | None] = _ts(nullable=True)

    tls_expires_at: Mapped[datetime | None] = _ts(nullable=True)
    tls_checked_at: Mapped[datetime | None] = _ts(nullable=True)

    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())


class CheckResult(Base):
    """단일 HTTP 검사 결과.

    outcome
    - up: 기대 상태코드 응답
    - down: 상태코드 불일치, 타임아웃, DNS/연결/TLS 오류, 차단된 주소 등 (대상 장애로 관측됨)
    - error: 검사기 내부 오류 등 측정 불가 (가동률 분모·분자 모두에서 제외, 커버리지 감소)
    """

    __tablename__ = "check_results"
    __table_args__ = (
        Index("ix_check_results_monitor_time", "monitor_id", "checked_at"),
        Index("ix_check_results_checked_at", "checked_at"),  # 보관 기간 정리용
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = _ts()
    outcome: Mapped[str] = mapped_column(String(8))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(500))
    redirect_count: Mapped[int] = mapped_column(Integer, default=0)
    tls_expires_at: Mapped[datetime | None] = _ts(nullable=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # 모니터당 진행 중 장애는 최대 1개
        Index(
            "uq_incidents_one_open_per_monitor",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index("ix_incidents_monitor_started", "monitor_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = _ts()  # 연속 실패의 첫 실패 시각
    detected_at: Mapped[datetime] = _ts()  # 기준 횟수에 도달해 장애로 판정된 시각
    resolved_at: Mapped[datetime | None] = _ts(nullable=True)  # 복구 첫 성공 시각
    cause_type: Mapped[str | None] = mapped_column(String(32))
    cause_message: Mapped[str | None] = mapped_column(String(500))
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)
    last_reminder_at: Mapped[datetime | None] = _ts(nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    monitor: Mapped[Monitor] = relationship(lazy="raise")

    @property
    def duration_seconds(self) -> int | None:
        if self.resolved_at is None:
            return None
        return max(0, int((self.resolved_at - self.started_at).total_seconds()))


class Notification(Base):
    """대시보드 알림. 같은 dedupe_key 의 알림은 사용자당 한 번만 생성됩니다."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    monitor_id: Mapped[int | None] = mapped_column(ForeignKey("monitors.id", ondelete="SET NULL"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24))  # down | up | reminder | tls_expiring | test
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    read_at: Mapped[datetime | None] = _ts(nullable=True)


class NotificationDelivery(Base):
    """외부 채널(이메일) 발송 기록. 실패·건너뜀·중복 제한도 모두 기록합니다."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_deliveries_pending", "status", "next_attempt_at"),
        Index("ix_deliveries_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    monitor_id: Mapped[int | None] = mapped_column(ForeignKey("monitors.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24))
    channel: Mapped[str] = mapped_column(String(16), default="email")
    recipient: Mapped[str] = mapped_column(String(254))
    # pending | sent | failed | skipped(미연동) | suppressed(중복 제한)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    next_attempt_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    sent_at: Mapped[datetime | None] = _ts(nullable=True)
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())


class StatusPage(Base):
    __tablename__ = "status_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    show_uptime: Mapped[bool] = mapped_column(Boolean, default=True)
    show_response_times: Mapped[bool] = mapped_column(Boolean, default=False)
    show_incidents: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())

    items: Mapped[list[StatusPageMonitor]] = relationship(
        cascade="all, delete-orphan", order_by="StatusPageMonitor.sort_order", lazy="selectin"
    )


class StatusPageMonitor(Base):
    __tablename__ = "status_page_monitors"

    status_page_id: Mapped[int] = mapped_column(
        ForeignKey("status_pages.id", ondelete="CASCADE"), primary_key=True
    )
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), primary_key=True)
    # 공개 페이지에 표시할 이름 (URL·내부 이름 대신 사용)
    display_name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    checks_performed: Mapped[int] = mapped_column(BigInteger, default=0)
