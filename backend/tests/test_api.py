"""API: 인증, CSRF, 사용자별 데이터 분리, 모니터 관리, 상태 페이지 공개 정보 제한."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import CheckResult, Incident, Monitor

MONITOR = {
    "name": "공개 웹사이트",
    "description": "메인 홈페이지",
    "url": "https://public.example/health",
    "interval_seconds": 60,
    "timeout_seconds": 10,
    "expected_status": "200-299",
    "failure_threshold": 3,
}


# ---------- 인증 ----------
async def test_register_login_logout_flow(make_client, register) -> None:
    user = await register("bob@example.com", "s3cret-password")
    me = await user.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "bob@example.com"

    # 세션 쿠키는 HttpOnly
    set_cookie = (await make_client().post("/api/auth/login", json={"email": "bob@example.com", "password": "s3cret-password"})).headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("uw_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie

    assert (await user.post("/api/auth/logout")).status_code == 204
    assert (await user.get("/api/auth/me")).status_code == 401


async def test_login_wrong_password_and_rate_limit(register, make_client) -> None:
    await register("carol@example.com", "right-password")
    client = make_client()
    r = await client.post("/api/auth/login", json={"email": "carol@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert "올바르지 않습니다" in r.json()["detail"]
    for _ in range(9):
        await client.post("/api/auth/login", json={"email": "carol@example.com", "password": "wrong"})
    r = await client.post("/api/auth/login", json={"email": "carol@example.com", "password": "right-password"})
    assert r.status_code == 429


async def test_duplicate_registration_and_weak_password(register, make_client) -> None:
    await register("dave@example.com")
    client = make_client()
    r = await client.post("/api/auth/register", json={"email": "dave@example.com", "password": "another-pass"})
    assert r.status_code == 409
    r = await client.post("/api/auth/register", json={"email": "eve@example.com", "password": "short"})
    assert r.status_code == 422 and "8자" in r.json()["detail"]


async def test_password_is_hashed_with_argon2(register, sessionmaker) -> None:
    from app.models import User

    await register("frank@example.com", "plain-text-pw")
    async with sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == "frank@example.com"))
        assert user.password_hash.startswith("$argon2id$")
        assert "plain-text-pw" not in user.password_hash


async def test_unauthenticated_requests_rejected(make_client) -> None:
    client = make_client()
    for path in ("/api/monitors", "/api/dashboard", "/api/incidents", "/api/notifications", "/api/status-pages"):
        assert (await client.get(path)).status_code == 401


async def test_csrf_token_required_for_mutations(register) -> None:
    user = await register()
    r = await user.client.post("/api/monitors", json=MONITOR)  # CSRF 헤더 없음
    assert r.status_code == 403
    r = await user.client.post("/api/monitors", json=MONITOR, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert (await user.post("/api/monitors", json=MONITOR)).status_code == 201


async def test_cross_origin_mutation_rejected(register) -> None:
    user = await register()
    r = await user.client.post(
        "/api/monitors", json=MONITOR, headers={"X-CSRF-Token": user.csrf, "Origin": "https://evil.example"}
    )
    assert r.status_code == 403


# ---------- 모니터 관리 ----------
async def test_monitor_crud(register) -> None:
    user = await register()
    r = await user.post("/api/monitors", json=MONITOR)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["status"] == "pending" and created["next_check_at"] is not None
    mid = created["id"]

    r = await user.patch(f"/api/monitors/{mid}", json={"name": "변경된 이름", "interval_seconds": 120, "expected_status": "200, 301-302"})
    assert r.status_code == 200
    assert r.json()["name"] == "변경된 이름" and r.json()["expected_status"] == "200,301-302"

    r = await user.post(f"/api/monitors/{mid}/pause")
    assert r.json()["status"] == "paused" and r.json()["is_active"] is False
    assert (await user.post(f"/api/monitors/{mid}/check")).status_code == 409
    r = await user.post(f"/api/monitors/{mid}/resume")
    assert r.json()["status"] == "pending" and r.json()["is_active"] is True

    assert len((await user.get("/api/monitors")).json()) == 1
    assert (await user.delete(f"/api/monitors/{mid}")).status_code == 204
    assert (await user.get(f"/api/monitors/{mid}")).status_code == 404


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"interval_seconds": 30}, "확인 주기"),
        ({"timeout_seconds": 0}, "타임아웃"),
        ({"timeout_seconds": 31}, "타임아웃"),
        ({"expected_status": "abc"}, "상태 코드"),
        ({"expected_status": "700"}, "100~599"),
        ({"failure_threshold": 0}, "연속 실패 기준"),
        ({"method": "POST"}, "요청 방식"),
    ],
)
async def test_monitor_validation(register, patch, message) -> None:
    user = await register()
    r = await user.post("/api/monitors", json={**MONITOR, **patch})
    assert r.status_code == 422
    assert message in r.json()["detail"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost:8080/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://2130706433/",
        "http://intranet/",
        "http://user:pw@public.example/",
        "ftp://public.example/",
        "http://public.example:22/",
        "https://evil.example/",  # 가짜 DNS → 10.0.0.5
        "https://mixed.example/",  # 공인 + 사설 혼합
    ],
)
async def test_ssrf_targets_rejected_by_api(register, url) -> None:
    user = await register()
    r = await user.post("/api/monitors", json={**MONITOR, "url": url})
    assert r.status_code == 422, r.text
    r2 = await user.post("/api/monitors", json=MONITOR)
    r3 = await user.patch(f"/api/monitors/{r2.json()['id']}", json={"url": url})
    assert r3.status_code == 422


async def test_unresolvable_domain_can_be_registered(register) -> None:
    """DNS 가 아직 없어도 등록은 가능(검사 시 DNS 오류로 기록)."""
    user = await register()
    r = await user.post("/api/monitors", json={**MONITOR, "url": "https://not-yet-live.example/"})
    assert r.status_code == 201


async def test_monitor_limit_per_user(register, app) -> None:
    from app.config import get_settings

    user = await register()
    original = get_settings().max_monitors_per_user
    get_settings().max_monitors_per_user = 2
    try:
        for _ in range(2):
            assert (await user.post("/api/monitors", json=MONITOR)).status_code == 201
        r = await user.post("/api/monitors", json=MONITOR)
        assert r.status_code == 422 and "최대 2개" in r.json()["detail"]
    finally:
        get_settings().max_monitors_per_user = original


async def test_manual_check_cooldown(register) -> None:
    user = await register()
    mid = (await user.post("/api/monitors", json=MONITOR)).json()["id"]
    assert (await user.post(f"/api/monitors/{mid}/check")).status_code == 202
    r = await user.post(f"/api/monitors/{mid}/check")
    assert r.status_code == 429 and "Retry-After" in r.headers


# ---------- 사용자별 데이터 분리 ----------
async def test_users_cannot_access_each_others_data(register, sessionmaker) -> None:
    alice = await register("alice@example.com")
    mallory = await register("mallory@example.com")
    mid = (await alice.post("/api/monitors", json=MONITOR)).json()["id"]

    async with sessionmaker() as db:  # 장애 기록을 하나 만들어 둔다
        now = datetime.now(UTC)
        db.add(Incident(monitor_id=mid, started_at=now - timedelta(minutes=5), detected_at=now, failed_checks=3))
        db.add(CheckResult(monitor_id=mid, checked_at=now, outcome="down", status_code=500, response_time_ms=10, redirect_count=0, is_manual=False))
        await db.commit()

    assert (await mallory.get("/api/monitors")).json() == []
    for method, path in [
        ("get", f"/api/monitors/{mid}"),
        ("patch", f"/api/monitors/{mid}"),
        ("delete", f"/api/monitors/{mid}"),
        ("post", f"/api/monitors/{mid}/pause"),
        ("post", f"/api/monitors/{mid}/check"),
        ("get", f"/api/monitors/{mid}/checks"),
        ("get", f"/api/monitors/{mid}/stats"),
        ("get", f"/api/monitors/{mid}/response-times"),
        ("get", f"/api/monitors/{mid}/daily-uptime"),
        ("get", f"/api/monitors/{mid}/incidents"),
    ]:
        kwargs = {"json": {"name": "hacked"}} if method == "patch" else {}
        r = await getattr(mallory, method)(path, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    assert (await mallory.get("/api/incidents")).json() == []
    assert (await mallory.get(f"/api/incidents?monitor_id={mid}")).json() == []
    dash = (await mallory.get("/api/dashboard")).json()
    assert dash["counts"]["total"] == 0 and dash["open_incidents"] == []

    # 다른 사용자의 모니터를 자기 상태 페이지에 넣을 수 없음
    r = await mallory.post(
        "/api/status-pages",
        json={"slug": "steal", "title": "x", "items": [{"monitor_id": mid, "display_name": "x"}]},
    )
    assert r.status_code == 422

    async with sessionmaker() as db:
        monitor = await db.get(Monitor, mid)
        assert monitor.name == MONITOR["name"]  # 변경되지 않음
    assert len((await alice.get("/api/incidents")).json()) == 1


# ---------- 상태 페이지 ----------
async def test_public_status_page_exposes_only_selected_safe_fields(register, make_client, sessionmaker) -> None:
    owner = await register()
    shown = (await owner.post("/api/monitors", json=MONITOR)).json()["id"]
    hidden = (await owner.post("/api/monitors", json={**MONITOR, "name": "비공개 관리자 API", "url": "https://public.example/admin?token=SECRET123"})).json()["id"]

    async with sessionmaker() as db:
        now = datetime.now(UTC)
        db.add(CheckResult(monitor_id=shown, checked_at=now, outcome="down", status_code=500, response_time_ms=10, error_type="status", error_message="예상하지 않은 HTTP 상태 코드 500", redirect_count=0, is_manual=False))
        db.add(Incident(monitor_id=shown, started_at=now - timedelta(minutes=3), detected_at=now, cause_type="status", cause_message="내부 오류 메시지", failed_checks=3))
        await db.commit()

    page = {
        "slug": "acme-status",
        "title": "ACME 서비스 상태",
        "description": "ACME 서비스 운영 현황",
        "is_published": False,
        "show_uptime": True,
        "show_response_times": True,
        "show_incidents": True,
        "items": [{"monitor_id": shown, "display_name": "웹사이트"}],
    }
    r = await owner.post("/api/status-pages", json=page)
    assert r.status_code == 201, r.text
    page_id = r.json()["id"]

    anon = make_client()
    assert (await anon.get("/api/public/status/acme-status")).status_code == 404  # 미게시
    await owner.put(f"/api/status-pages/{page_id}", json={**page, "is_published": True})

    r = await anon.get("/api/public/status/acme-status")
    assert r.status_code == 200
    assert "public" in r.headers["cache-control"]
    body = r.json()
    raw = r.text
    assert body["title"] == "ACME 서비스 상태"
    assert [c["name"] for c in body["components"]] == ["웹사이트"]
    assert body["incidents"][0]["component"] == "웹사이트"
    # 내부 정보 미노출: URL·호스트·오류 메시지·상태 코드·모니터 ID·비공개 모니터
    for secret in ("public.example", "SECRET123", "비공개 관리자 API", "내부 오류 메시지", "상태 코드", "monitor_id", "url", "error"):
        assert secret not in raw, secret
    component = body["components"][0]
    assert set(component) == {"key", "name", "status", "last_checked_at", "uptime", "daily", "response_times"}
    assert set(body["incidents"][0]) == {"component", "started_at", "resolved_at", "duration_seconds", "ongoing"}
    assert hidden not in [c.get("key") for c in body["components"]]

    # 표시 옵션 끄면 해당 데이터 제거
    await owner.put(f"/api/status-pages/{page_id}", json={**page, "is_published": True, "show_uptime": False, "show_response_times": False, "show_incidents": False})
    body = (await anon.get("/api/public/status/acme-status")).json()
    assert "uptime" not in body["components"][0] and "response_times" not in body["components"][0]
    assert body["incidents"] == []


async def test_status_page_slug_unique_and_validated(register) -> None:
    a = await register("a@example.com")
    b = await register("b@example.com")
    assert (await a.post("/api/status-pages", json={"slug": "shared", "title": "A"})).status_code == 201
    assert (await b.post("/api/status-pages", json={"slug": "shared", "title": "B"})).status_code == 409
    assert (await b.post("/api/status-pages", json={"slug": "Bad Slug!", "title": "B"})).status_code == 422
    # b 는 a 의 상태 페이지를 조회·수정·삭제할 수 없음
    page_id = (await a.get("/api/status-pages")).json()[0]["id"]
    assert (await b.get(f"/api/status-pages/{page_id}")).status_code == 404
    assert (await b.delete(f"/api/status-pages/{page_id}")).status_code == 404


# ---------- 알림 ----------
async def test_test_notification_when_email_not_configured(register) -> None:
    user = await register()
    channels = (await user.get("/api/notifications/channels")).json()
    assert channels["email"]["configured"] is False and channels["email"]["status"] == "not_configured"

    r = await user.post("/api/notifications/test")
    assert r.status_code == 200
    body = r.json()
    assert body["dashboard"]["status"] == "created"
    assert body["email"]["status"] == "skipped" and "미연동" in body["email"]["error"]
    # 빈도 제한
    assert (await user.post("/api/notifications/test")).status_code == 429

    notes = (await user.get("/api/notifications")).json()
    assert notes[0]["kind"] == "test" and notes[0]["read_at"] is None
    deliveries = (await user.get("/api/notifications/deliveries")).json()
    assert deliveries[0]["status"] == "skipped"

    await user.post(f"/api/notifications/{notes[0]['id']}/read")
    assert (await user.get("/api/dashboard")).json()["unread_notifications"] == 0


async def test_notification_settings_roundtrip(register) -> None:
    user = await register()
    r = await user.put(
        "/api/notifications/settings",
        json={"email_enabled": True, "email_to": "Ops@Example.com", "email_cooldown_minutes": 15, "reminder_interval_minutes": 60, "tls_warning_days": 21},
    )
    assert r.status_code == 200
    s = (await user.get("/api/notifications/settings")).json()
    assert s["email_to"] == "ops@example.com" and s["reminder_interval_minutes"] == 60
    assert (await user.put("/api/notifications/settings", json={"email_to": "not-an-email"})).status_code == 422


async def test_health_endpoint(make_client) -> None:
    r = await make_client().get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
