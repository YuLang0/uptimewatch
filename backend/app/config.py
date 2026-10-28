"""애플리케이션 설정.

모든 설정은 환경변수(또는 .env 파일)에서 읽습니다. 비밀정보(SMTP 비밀번호, SECRET_KEY 등)는
데이터베이스에 저장하지 않고 환경변수로만 주입합니다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "UptimeWatch"
    environment: str = "development"  # development | production | test
    database_url: str = "postgresql+asyncpg://uptimewatch:uptimewatch@localhost:5432/uptimewatch"
    secret_key: SecretStr = SecretStr("dev-insecure-secret-change-me")
    public_base_url: str = "http://localhost:8080"
    display_timezone: str = "Asia/Seoul"

    # 인증
    cookie_secure: bool = False
    session_ttl_hours: int = 24 * 7
    allow_registration: bool = True
    # 쉼표로 구분한 추가 허용 Origin (CSRF Origin 검사용). public_base_url 은 항상 허용.
    extra_allowed_origins: str = ""
    login_rate_limit_per_15min: int = 10
    register_rate_limit_per_hour: int = 5

    # 검사기(Checker)
    check_min_interval_seconds: int = 60
    check_max_interval_seconds: int = 86_400
    check_min_timeout_seconds: int = 1
    check_max_timeout_seconds: int = 30
    check_max_response_bytes: int = 1_048_576
    check_max_redirects: int = 5
    # 검사 허용 포트. 빈 값이면 모든 포트 허용(권장하지 않음).
    check_allowed_ports: str = "80,443,8080,8443"
    # 위험: 사설망 예외 CIDR. 테스트/모의 서버 환경에서만 사용하세요.
    check_allowed_cidrs: str = ""
    # 선택: 외부 송신(egress) 프록시. 설정 시 DNS 해석과 최종 송신 필터링을 프록시가 담당합니다.
    check_egress_proxy: str | None = None
    check_user_agent: str = "UptimeWatch/1.0 (uptime monitor)"
    check_concurrency: int = 20
    check_per_host_per_minute: int = 30
    manual_check_cooldown_seconds: int = 30
    max_monitors_per_user: int = 50

    # 작업자(Worker)
    worker_tick_seconds: float = 2.0
    worker_batch_size: int = 50
    worker_heartbeat_seconds: int = 15
    worker_stale_after_seconds: int = 60
    check_retention_days: int = 90
    notification_retention_days: int = 180

    # 이메일 (SMTP) — 미설정 시 "미연동" 상태로 표시
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: int = 15
    email_max_per_hour_per_user: int = 30
    notification_max_attempts: int = 3
    test_notification_cooldown_seconds: int = 60

    @field_validator("smtp_host", "smtp_from", "smtp_username", "check_egress_proxy", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def allowed_ports(self) -> frozenset[int] | None:
        ports = _split_csv(self.check_allowed_ports)
        return frozenset(int(p) for p in ports) if ports else None

    @property
    def allowed_cidrs(self) -> list[str]:
        return _split_csv(self.check_allowed_cidrs)

    @property
    def allowed_origins(self) -> set[str]:
        origins = {self.public_base_url.rstrip("/")}
        origins.update(o.rstrip("/") for o in _split_csv(self.extra_allowed_origins))
        return origins

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
