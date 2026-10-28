# UptimeWatch — 웹사이트 가동률 및 장애 감지 서비스

[![CI](https://github.com/YuLang0/uptimewatch/actions/workflows/ci.yml/badge.svg)](https://github.com/YuLang0/uptimewatch/actions/workflows/ci.yml)

내가 관리하는 웹사이트에 **실제 HTTP/HTTPS 요청**을 주기적으로 보내 응답 상태·응답 시간·TLS 인증서 만료일을 기록하고,
연속 실패로 장애를 판정해 **대시보드·이메일 알림**을 보내며, **공개 상태 페이지**로 서비스 상태를 공유하는 모니터링 플랫폼입니다.

| 영역 | 기술 |
|---|---|
| 프론트엔드 | React 18 + TypeScript, Tailwind CSS, TanStack Query, Recharts, Vite |
| 백엔드 | FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, HTTPX/httpcore |
| 작업자 | APScheduler(AsyncIO) + DB 기반 스케줄(`monitors.next_check_at`) |
| 데이터베이스 | PostgreSQL 16 |
| 배포 | Docker Compose (db · migrate · api · worker · web(nginx) · caddy(선택)) |
| 테스트 | Pytest(백엔드 151개) · Vitest(28개) · Playwright E2E(7개) |

> **바로 실행:** `./scripts/setup.sh` → <http://localhost:8080> (자세한 내용은 [3. 빠른 시작](#3-빠른-시작-docker-compose))
>
> **서버 배포:** 오라클 클라우드 무료 서버에 올리는 단계별 안내 → [docs/deploy-oracle.md](docs/deploy-oracle.md)

| 대시보드 | 모니터 상세(다크 모드) | 공개 상태 페이지 |
|---|---|---|
| ![대시보드](docs/screenshots/dashboard-light.png) | ![모니터 상세](docs/screenshots/monitor-dark.png) | ![공개 상태 페이지](docs/screenshots/public-status-light.png) |

---

## 1. 주요 기능

**모니터링 대상** — URL·이름·설명 등록, 확인 주기(최소 60초), 타임아웃(1~30초), 기대 상태 코드(`200-299,301` 형식),
GET/HEAD, 리다이렉트 추적 여부, 연속 실패/복구 기준, 활성화·일시 정지, 수정·삭제, '지금 검사'(빈도 제한).

**웹사이트 검사** — 실제 HTTP/HTTPS 요청, 상태 코드, 응답 시간, 연결 오류·타임아웃·DNS 오류·TLS 오류 구분,
TLS 인증서 만료일, 마지막 검사 시각, 연속 실패 횟수.

**장애 감지** — 연속 실패 기준 도달 시 장애 생성(시작 시각 = 연속 실패의 첫 실패), 복구 기준 도달 시 복구(복구 시각 = 연속 성공의 첫 성공),
지속 시간, 기준 미만 실패는 '일시적 실패(불안정)'로만 기록, 장애 기록은 삭제하지 않고 보관.

**통계** — 24시간/7일/30일 가동률, 측정 커버리지, 평균·최대·최소·p95 응답 시간, 장애 횟수·누적 중단 시간,
기간별 응답 시간 그래프(30일은 날짜별), 90일 일별 가동률 막대.

**알림** — 대시보드 알림(읽음 처리), 이메일(SMTP), 장애/복구 1회 알림(중복 생성 방지), 같은 종류 메일 재발송 제한(분),
시간당 발송 한도, 장애 지속 재알림(선택), TLS 만료 임박 경고, 발송 실패 기록·재시도(최대 3회), 테스트 알림.
SMTP 를 설정하지 않으면 화면에 **'미연동'** 으로 표시되고 발송 기록에도 '미연동'으로 남습니다.

**상태 페이지** — 관리자가 고른 모니터와 공개 항목(가동률·응답 시간·장애 이력)만 표시, 공개 이름 사용,
URL·오류 상세·상태 코드·내부 ID 비공개, 로그인 영역과 완전히 분리된 라우트·API(`/status/:slug`, `/api/public/*`).

**UI** — UptimeRobot 류의 상태 카드·24시간 상태 띠·90일 막대, 응답 시간 그래프(표 보기 지원), 장애 타임라인,
다크 모드(시스템 설정 연동 + 수동 전환), 한국어, 모바일 하단 탭 레이아웃.

---

## 2. 아키텍처

```
 브라우저 ──HTTPS──▶ caddy(선택, 자동 인증서) ──▶ web(nginx: SPA + /api 프록시, 요청 제한)
                                                     │
                                                     ▼
                                           api (FastAPI, uvicorn)
                                                     │  SQL
             인터넷의 대상 사이트 ◀──HTTP(S)── worker ─┼──▶ db (PostgreSQL, internal 네트워크 전용)
             (SSRF 정책 통과 대상만)          (APScheduler)
```

- **api** 는 외부로 검사 요청을 보내지 않습니다. '지금 검사'도 `next_check_at` 만 당겨 두고 **worker** 가 수행합니다.
- **worker** 는 `SELECT … FOR UPDATE SKIP LOCKED` 로 검사 대상을 선점하므로 여러 개를 띄워도 중복 검사하지 않습니다.
- 스케줄이 DB 에 저장되므로 **프로세스·서버가 재시작돼도 이어서 검사**합니다. 재시작 시 밀린 검사는 최대 30초 구간에 분산 예약됩니다.
- **db** 는 `internal: true` 네트워크에만 연결되어 웹 컨테이너·외부에서 접근할 수 없습니다.

### 디렉터리

```
uptimewatch/
├── docker-compose.yml        # 전체 서비스 정의
├── .env.example              # 환경변수 템플릿
├── deploy/Caddyfile          # HTTPS 리버스 프록시(선택)
├── scripts/setup.sh         # 한 번에 설치·실행 (--domain 으로 HTTPS 배포)
├── scripts/server-init.sh   # 새 서버 초기 설정(방화벽·스왑·Docker)
├── docs/deploy-oracle.md    # 오라클 무료 서버 배포 안내
├── scripts/backup.sh, restore.sh
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI 앱, 보안 헤더·Origin 검사, 오류 메시지 한글화
│   │   ├── config.py         # 환경변수 설정
│   │   ├── models.py         # DB 모델
│   │   ├── api/              # auth · monitors · overview · notifications · status_pages(관리/공개)
│   │   ├── security/         # ssrf.py(SSRF 정책) · auth.py(Argon2id·세션·CSRF) · rate_limit.py
│   │   ├── services/         # checker.py(HTTP 검사) · monitoring.py(장애 판정) · stats.py(가동률)
│   │   │                     # notifications.py(알림·중복 제한) · email.py(SMTP)
│   │   └── worker/           # runner.py(스케줄러) · __main__.py · healthcheck.py
│   ├── alembic/              # 마이그레이션
│   └── tests/                # pytest + 모의 HTTP/SMTP 서버
└── frontend/
    ├── src/pages/            # 대시보드·모니터 상세/편집·장애·알림·상태 페이지·공개 상태 페이지
    ├── src/components/       # 상태 배지·가동률 막대·응답 시간 그래프·타임라인·폼
    ├── e2e/                  # Playwright E2E
    └── nginx.conf
```

---

## 3. 빠른 시작 (Docker Compose)

### 방법 A — 스크립트 한 번 (권장, Linux·macOS·Windows WSL2)

```bash
unzip uptimewatch.zip && cd uptimewatch
./scripts/setup.sh
```
`.env` 가 없으면 `.env.example` 을 복사해 **DB 비밀번호·SECRET_KEY 를 무작위로 채우고**, 이미지를 빌드해 전체 서비스를 띄운 뒤
헬스체크까지 확인합니다. 완료되면 <http://localhost:8080> 에서 회원가입 → '새 모니터'로 사이트를 등록하세요.

### 방법 B — 직접 실행 (Windows PowerShell 등)

```bash
cp .env.example .env
# .env 에서 POSTGRES_PASSWORD, SECRET_KEY 를 반드시 긴 임의 문자열로 변경
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # 값 생성용

docker compose up -d --build
docker compose ps          # api·worker 가 healthy 인지 확인
# 브라우저: http://localhost:8080
```

시작 순서: `db`(healthy) → `migrate`(alembic upgrade head, 1회 실행 후 종료) → `api`·`worker` → `web`.

### 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 보기 | `docker compose ps` |
| 로그 보기 | `docker compose logs -f api worker` |
| 중지 / 다시 시작 | `docker compose stop` / `docker compose start` |
| 설정(.env) 변경 반영 | `docker compose up -d` |
| 코드 업데이트 반영 | `docker compose up -d --build` |
| 작업자 늘리기 | `docker compose up -d --scale worker=2` |
| 백업 / 복원 | `./scripts/backup.sh` / `./scripts/restore.sh backups/<파일>.dump` |
| 완전 삭제(데이터 포함, 주의) | `docker compose down -v` |

> **주의** — DB 비밀번호는 `pgdata` 볼륨을 처음 만들 때 정해집니다. 나중에 `.env` 의 `POSTGRES_PASSWORD` 만 바꾸면
> api 가 DB 에 접속하지 못합니다. 비밀번호를 바꾸려면 DB 안에서 `ALTER USER` 로 함께 바꾸세요.
>
> TLS 를 가로채는 사내 프록시 환경에서 빌드 중 pip/npm 인증서 오류가 나면, CA 파일을 프로젝트의 `deploy/` 안에 복사한 뒤
> 지정하세요(이미지에 남지 않습니다):
> `cp /path/corp-ca.pem deploy/extra-ca.pem && EXTRA_CA_FILE=./deploy/extra-ca.pem ./scripts/setup.sh`

### 환경변수 요약

| 변수 | 기본값 | 설명 |
|---|---|---|
| `POSTGRES_PASSWORD` | (필수) | DB 비밀번호 |
| `SECRET_KEY` | (운영 필수) | CSRF 토큰 HMAC 키. 운영(`ENVIRONMENT=production`)에서 기본값이면 기동 거부 |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | 사용자가 접속하는 주소(이메일 링크·Origin 검사) |
| `EXTRA_ALLOWED_ORIGINS` | | 추가 허용 Origin(쉼표 구분) |
| `COOKIE_SECURE` | `false` | HTTPS 운영 시 `true` |
| `ALLOW_REGISTRATION` | `true` | 공개 회원가입 허용 여부 |
| `DISPLAY_TIMEZONE` | `Asia/Seoul` | 일별 통계 기준 시간대 |
| `CHECK_MIN_INTERVAL_SECONDS` | `60` | 최소 확인 주기 |
| `CHECK_MAX_TIMEOUT_SECONDS` | `30` | 최대 타임아웃 |
| `CHECK_MAX_RESPONSE_BYTES` | `1048576` | 응답 본문 최대 읽기 크기(초과분은 읽지 않음) |
| `CHECK_MAX_REDIRECTS` | `5` | 리다이렉트 최대 횟수 |
| `CHECK_ALLOWED_PORTS` | `80,443,8080,8443` | 검사 허용 포트 |
| `CHECK_CONCURRENCY` | `20` | 작업자 동시 검사 수 |
| `CHECK_PER_HOST_PER_MINUTE` | `30` | 같은 호스트에 대한 분당 최대 검사 수(전체 사용자 합산, 초과분은 연기) |
| `MAX_MONITORS_PER_USER` | `50` | 사용자당 모니터 수 |
| `MANUAL_CHECK_COOLDOWN_SECONDS` | `30` | '지금 검사' 최소 간격 |
| `CHECK_RETENTION_DAYS` | `90` | 원본 검사 결과 보관 기간(장애 기록은 보관) |
| `CHECK_ALLOWED_CIDRS` | (비움) | **위험**: 사설망 예외. 테스트·모의 서버 전용 |
| `CHECK_EGRESS_PROXY` | (비움) | 선택: 송신 프록시. 아래 '보안' 참고 |
| `SMTP_*`, `EMAIL_MAX_PER_HOUR_PER_USER` | | 이메일 설정(아래) |

---

## 4. 이메일 알림(SMTP) 설정

`SMTP_HOST` 와 `SMTP_FROM` 이 비어 있으면 이메일은 **미연동** 상태입니다. 이때도 대시보드 알림은 정상 동작하며,
'알림 → 설정' 화면에 '미연동' 배지와 필요한 환경변수가 표시되고, 발송 기록에는 `미연동(skipped)`으로 남습니다.

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=alerts@example.com
SMTP_PASSWORD=앱-비밀번호
SMTP_FROM=UptimeWatch <alerts@example.com>
SMTP_STARTTLS=true     # 587 포트
SMTP_SSL=false         # 465 포트를 쓰면 STARTTLS=false, SSL=true
```

| 서비스 | HOST / PORT | 참고 |
|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` / 587 | 2단계 인증 후 **앱 비밀번호** 사용 |
| 네이버 메일 | `smtp.naver.com` / 587 | 메일 환경설정에서 POP3/SMTP 사용 설정 |
| Amazon SES | `email-smtp.<region>.amazonaws.com` / 587 | SMTP 자격 증명 생성, 발신 도메인 인증 |

설정 후 `docker compose up -d api worker` 로 재시작 → '알림 → 설정 → 테스트 알림 보내기'로 실제 발송을 확인합니다.
SMTP 비밀번호는 **환경변수로만** 주입되며 DB·로그에 저장하지 않습니다(오류 기록에는 예외 종류와 요약만 저장).

---

## 5. HTTPS 리버스 프록시

> 새 Ubuntu 서버라면 `sudo ./scripts/server-init.sh` 후 `./scripts/setup.sh --domain <도메인>` 한 줄로 아래 방법 A 가 자동 설정됩니다.
> 오라클 무료 서버 기준 전체 과정: [docs/deploy-oracle.md](docs/deploy-oracle.md)

### 방법 A — 포함된 Caddy (자동 Let's Encrypt)

```bash
# .env
DOMAIN=status.example.com
PUBLIC_BASE_URL=https://status.example.com
COOKIE_SECURE=true
WEB_BIND=127.0.0.1           # 평문 8080 은 로컬에만 노출

docker compose --profile https up -d --build
```
도메인의 A/AAAA 레코드가 서버를 가리키고 80/443 포트가 열려 있어야 합니다. 인증서는 `caddy_data` 볼륨에 보관됩니다.

### 방법 B — 기존 Nginx + certbot

```nginx
server {
    listen 443 ssl http2;
    server_name status.example.com;
    ssl_certificate     /etc/letsencrypt/live/status.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/status.example.com/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;   # 클라이언트가 보낸 값은 덮어씀
        proxy_set_header X-Forwarded-Proto https;
    }
}
server { listen 80; server_name status.example.com; return 301 https://$host$request_uri; }
```
(`web` 컨테이너의 nginx 는 도커 사설망에서 온 `X-Forwarded-For` 만 신뢰합니다. 호스트의 nginx 에서 넘길 때는
`WEB_BIND=127.0.0.1` 을 유지하고, 필요하면 `frontend/nginx.conf` 의 `set_real_ip_from` 에 프록시 주소를 추가하세요.)

---

## 6. 백그라운드 작업자

- 실행: compose 의 `worker` 서비스(`python -m app.worker`). 로컬에서는 `cd backend && python -m app.worker`.
- 주기 작업(APScheduler): 디스패치(2초) · 이메일 발송(10초) · 하트비트(15초) · 정리(6시간: 보관 기간 지난 검사 결과·만료 세션 삭제).
- 하트비트가 60초 이상 끊기면 대시보드 상단에 **'검사 작업자가 응답하지 않습니다'** 경고가 표시됩니다.
  그 기간의 공백은 가동률에서 정상으로 간주되지 않습니다(아래 7장).
- 종료 시(SIGTERM) 진행 중 검사를 마무리할 때까지 최대 35초 기다립니다(`stop_grace_period: 40s`).
- 수평 확장: `docker compose up -d --scale worker=2` — `SKIP LOCKED` 덕분에 중복 검사가 없습니다
  (호스트별 분당 제한은 작업자 프로세스 단위로 적용).

### 서버 재시작 후 검사 재개
모든 서비스는 `restart: unless-stopped` 입니다. Docker 데몬이 부팅 시 시작되도록(`systemctl enable docker`) 설정하면
서버 재부팅 후 자동으로 올라오며, 작업자는 DB 의 `next_check_at` 을 기준으로 밀린 검사를 분산 예약한 뒤 정상 주기로 돌아갑니다.

---

## 7. 가동률·응답 시간 계산

```
가동률 = up 검사 수 / (up 검사 수 + down 검사 수)        ← 관측한 결과만 사용
측정 커버리지 = 관측된 검사 수 / (관측 가능 기간 ÷ 확인 주기)
```

- **검사 공백**(작업자 중단·일시 정지·모니터 생성 전)은 분자·분모 어디에도 들어가지 않으며 **정상으로 간주하지 않습니다.**
  대신 커버리지가 낮아지고, 그래프·막대에서 회색 '데이터 없음'으로 표시됩니다.
- **측정 불가**(`error`, 검사기 내부 오류)도 정상으로 세지 않고 제외합니다. 장애 판정 카운터에도 영향을 주지 않습니다.
- 관측값이 하나도 없으면 가동률은 `null` → 화면에 '데이터 없음'(100% 로 표시하지 않음).
- 화면의 백분율은 **내림** 처리합니다(99.999% 를 100% 로 반올림해 장애를 가리지 않도록).
- 응답 시간 통계는 HTTP 응답을 받은 검사만 대상으로 합니다(타임아웃·연결 실패 제외). 응답 시간 = DNS·연결·TLS·리다이렉트·본문(상한까지) 포함 전체 시간.

### 결과 분류

| outcome | 예 | 가동률 |
|---|---|---|
| `up` | 기대 상태 코드 응답 | 성공 |
| `down` | 상태 코드 불일치, 타임아웃, DNS 오류, 연결 거부, TLS 오류(만료·호스트 불일치·자체 서명), 차단된 주소로 해석, 리다이렉트 오류 | 실패 |
| `error` | 검사기 내부 오류 | 제외(측정 불가) |

---

## 8. 장애 판정·알림 규칙

1. 실패가 `failure_threshold` 회 **연속**되면 장애 생성 → 'down' 알림 1회 (`dedupe_key = incident:{id}:down`, DB 유니크 제약).
2. 기준 미만의 실패는 '불안정'으로 표시만 하고 장애·알림을 만들지 않습니다.
3. 장애 중 추가 실패는 알림을 만들지 않습니다(재알림 간격을 설정한 경우에만 'reminder').
4. 성공이 `recovery_threshold` 회 연속되면 복구 → 'up' 알림 1회.
5. 이메일 중복 제한: 같은 모니터의 같은 종류 메일을 `email_cooldown_minutes` 안에 다시 보내지 않고 `중복 제한(suppressed)` 으로 기록
   (장애↔복구가 반복되는 flapping 대비). 사용자당 시간당 발송 한도도 적용.
6. 이메일은 발송 기록을 먼저 저장(outbox)한 뒤 작업자가 발송합니다. 실패 시 1분·5분 후 재시도, 3회 실패하면 `실패(failed)` 로 기록.

---

## 9. 보안 설계

### SSRF 방어 (`backend/app/security/ssrf.py`, `services/checker.py`)
1. **URL 정책** — `http/https` 만, `user:pass@` 금지(비밀정보 저장 방지), 허용 포트만, 단일 라벨 호스트(`db`, `intranet`)·
   내부용 도메인(`localhost`, `*.local`, `*.internal`, `metadata.google.internal`, `host.docker.internal` 등) 금지,
   `127.1`·`2130706433`·`0x7f.1` 같은 비표준 숫자 IP 표기 금지, 공백·제어문자·역슬래시 금지, 2048자 제한.
2. **주소 정책** — DNS 로 해석한 **모든** 주소가 공인 주소여야 합니다(하나라도 내부면 차단). 루프백, 사설(10/8, 172.16/12, 192.168/16),
   CGNAT(100.64/10), 링크 로컬·클라우드 메타데이터(169.254.169.254, `fd00:ec2::254`), 멀티캐스트, 예약·문서용 대역,
   IPv4 매핑(`::ffff:`)·NAT64·6to4·Teredo 에 내장된 IPv4 까지 검사합니다.
3. **DNS 재바인딩 방지(IP 고정)** — httpcore 네트워크 백엔드(`SafeNetworkBackend`)가 연결 직전에 해석·검증한 **바로 그 IP 로 접속**합니다.
   DNS 를 두 번 조회하지 않으므로 검증 후 주소를 바꾸는 공격이 통하지 않습니다. TLS SNI·인증서 검증은 원래 호스트명으로 수행됩니다.
4. **리다이렉트 검증** — 자동 추적을 끄고 홉마다 1~3 을 다시 적용, 최대 5회, http/https 외 스킴 거부.
5. **요청 제한** — GET/HEAD 만, 고정 헤더(User-Agent·Accept)만 전송(사용자 정의 헤더·인증정보 미지원), 전체 검사 시간 상한(타임아웃),
   응답 본문 1MB 까지만 읽고 저장하지 않음, 응답 헤더 미저장, 주기 최소 60초, 수동 검사 쿨다운, 호스트별 분당 제한, 전역 동시성 제한.
6. **등록 시 + 검사 시 이중 검증** — 등록 때 내부 주소로 해석되면 거부하고, 검사할 때마다 다시 검증합니다.
7. **선택: 송신 프록시 모드**(`CHECK_EGRESS_PROXY`) — 사내 정책상 모든 외부 요청이 프록시를 거쳐야 할 때 사용합니다.
   이 모드에서는 URL 정책·리다이렉트 검증은 그대로 적용되지만 최종 DNS 해석은 프록시가 하므로,
   **프록시 쪽에서도 내부 대역 차단(예: Smokescreen)** 을 적용해야 동일한 수준의 방어가 됩니다.

### 인증·권한
- 비밀번호: **Argon2id** 해시. 존재하지 않는 계정도 더미 해시와 비교해 응답 시간으로 계정 존재를 추측하기 어렵게 함.
- 세션: 무작위 토큰을 **HttpOnly·SameSite=Lax** 쿠키로 발급, DB 에는 **SHA-256 해시만** 저장, 로그아웃 시 즉시 폐기.
- CSRF: 세션 토큰에서 HMAC 으로 파생한 토큰을 `X-CSRF-Token` 헤더로 요구 + 상태 변경 요청의 `Origin` 검사.
- 사용자별 분리: 모든 조회·수정 쿼리가 `user_id` 로 필터링되며, 다른 사용자의 리소스는 존재 여부도 드러내지 않도록 **404**.
  상태 페이지에 남의 모니터 ID 를 넣는 시도도 거부합니다.
- 요청 제한: 로그인(IP+이메일 15분 10회), 가입(IP 시간당 5회), 공개 페이지(IP 분당 120회), 테스트 알림, nginx `limit_req`.
- 보안 헤더: CSP(`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, Referrer-Policy, API 응답 `Cache-Control: no-store`.
- 운영 모드에서는 OpenAPI 문서(`/api/docs`)를 비활성화합니다.

### 공개 상태 페이지
공개 API 응답은 허용 목록 방식으로 직접 구성합니다: 공개 이름, 상태(정상/장애/점검 중/확인 중), 선택 시 가동률·일별 막대·응답 시간·
장애 시작/복구 시각·지속 시간. **URL·호스트·IP·오류 메시지·상태 코드·내부 모니터 ID·임계값·TLS 정보는 포함하지 않습니다.**

---

## 10. 백업 및 복원

```bash
./scripts/backup.sh                 # backups/uptimewatch_YYYYmmdd_HHMMSS.dump (pg_dump -Fc, 최근 14개 보관)
./scripts/restore.sh backups/uptimewatch_20261025_220000.dump   # 확인 후 api/worker 정지 → 복원 → 마이그레이션 → 재시작
```

정기 백업 예(cron, 매일 03:10): `10 3 * * * cd /opt/uptimewatch && ./scripts/backup.sh >> backups/backup.log 2>&1`

데이터는 `pgdata` 볼륨에 저장되어 `docker compose down` / 재빌드 후에도 유지됩니다(`down -v` 는 데이터 삭제이므로 주의).

### 업그레이드
```bash
git pull && docker compose up -d --build   # migrate 서비스가 새 마이그레이션을 먼저 적용
```

---

## 11. 로컬 개발

```bash
# PostgreSQL 준비 후
cd backend
python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://uptimewatch:uptimewatch@localhost:5432/uptimewatch
alembic upgrade head
uvicorn app.main:app --reload --port 8000     # API (문서: http://localhost:8000/api/docs)
python -m app.worker                          # 작업자 (다른 터미널)

cd ../frontend && npm install && npm run dev  # http://localhost:5173 (/api → 8000 프록시)
```

---

## 12. 테스트

실제 외부 사이트에 부하를 주지 않도록 **모든 실패·복구 시나리오는 로컬 모의 HTTP(S) 서버와 모의 SMTP 서버**로 재현합니다.
가짜 DNS 리졸버로 DNS 오류·내부 주소 응답·DNS 재바인딩을 재현합니다.

```bash
# 백엔드 (PostgreSQL 테스트 DB uptimewatch_test 필요)
cd backend && pytest -q

# 프론트엔드 단위/컴포넌트
cd frontend && npm test

# E2E (모의 대상 서버 + API + 작업자 + 빌드된 프론트엔드를 자동 기동, DB uptimewatch_e2e 필요)
cd frontend && npx playwright test
```

| 요구 항목 | 테스트 |
|---|---|
| 정상 HTTP 200 | `test_checker.py::test_http_200_is_up`, E2E 흐름 |
| HTTP 500 오류 | `test_http_500_is_down`, `test_worker.py`(500 연속) |
| 타임아웃 | `test_timeout`, 작업자 통합 테스트(지연 응답) |
| DNS 오류 | `test_dns_error` |
| 일시적 vs 연속 장애 | `test_incidents.py::test_transient_failure_does_not_open_incident`, `…open_incident_once`, E2E('불안정' → '장애') |
| 복구 감지 | `test_recovery_is_detected_with_duration`, 작업자 통합, E2E |
| 중복 알림 방지 | `…open_incident_once`(장애 지속 중 알림 1회), `test_flapping_emails_are_rate_limited`, `…idempotent`, E2E(장애·복구 각 1건) |
| 가동률 계산 | `test_stats.py`(공백·측정 불가 제외, 데이터 없음=null, 커버리지, 중단 시간, 시간대별 일 구분) |
| SSRF 차단 | `test_ssrf.py`(69개: IP 표기 변형·IPv6 내장·메타데이터·재바인딩·IP 고정·리다이렉트), `test_api.py`, E2E |
| 인증·권한 분리 | `test_api.py`(CSRF·Origin·로그인 제한·Argon2·사용자 간 404), E2E(다른 사용자 접근) |
| TLS | 만료일 기록·만료 인증서·호스트 불일치·신뢰되지 않은 인증서(trustme) |
| 이메일 | 모의 SMTP 발송 성공, 실패 재시도 후 'failed' 기록, 미연동 'skipped' |
| 재시작 후 재개 | `test_worker.py::test_resume_after_restart`, 두 작업자 중복 선점 방지 |
| 프론트엔드 E2E | 등록→정상→일시 실패→장애→복구→알림, SSRF 입력, 공개 페이지 정보 비노출, 사용자 분리, 이메일 미연동·테스트 알림, 다크 모드, 모바일 |

실행 결과는 [`TEST_RESULTS.md`](TEST_RESULTS.md) 에 정리했습니다.

### CI (GitHub Actions)
`main` 에 push 하거나 PR 을 열면 [`.github/workflows/ci.yml`](.github/workflows/ci.yml) 이 자동으로 실행됩니다.

| 작업 | 내용 |
|---|---|
| 백엔드 | PostgreSQL 서비스 컨테이너 + `ruff check` + `pytest` |
| 프론트엔드 | `tsc -b` + `vitest` + `vite build` |
| E2E | 모의 대상 서버·API·작업자·프론트엔드를 띄워 Playwright(Chromium) 실행, 실패 시 리포트 업로드 |
| Docker | `docker compose config` 검증 + 이미지 빌드 |

---

## 13. API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/register` · `/login` · `/logout`, GET `/api/auth/me` | 인증 |
| GET/POST | `/api/monitors` | 목록(24시간 가동률 포함)/등록 |
| GET/PATCH/DELETE | `/api/monitors/{id}` | 조회/수정/삭제 |
| POST | `/api/monitors/{id}/pause` · `/resume` · `/check` | 일시 정지·재개·지금 검사 |
| GET | `/api/monitors/{id}/checks` · `/stats` · `/response-times?range=24h\|7d\|30d` · `/daily-uptime?days=90` · `/incidents` | 기록·통계 |
| GET | `/api/dashboard`, `/api/incidents?state=` | 요약·장애 목록 |
| GET/POST | `/api/notifications`, `/{id}/read`, `/read-all`, `/deliveries`, `/channels`, `/settings`(PUT), `/test` | 알림 |
| GET/POST/PUT/DELETE | `/api/status-pages[/{id}]` | 상태 페이지 관리 |
| GET | `/api/public/status/{slug}` | 공개 상태(인증 불필요) |
| GET | `/api/health` | 헬스체크 |

---

## 14. 운영 메모 / 한계

- 로그인·공개 페이지 요청 제한은 프로세스 메모리 기반입니다. API 를 여러 개로 확장할 때는 nginx `limit_req`(포함됨)나 공용 저장소 기반 제한을 함께 쓰세요.
- 검사는 작업자가 위치한 네트워크에서 수행됩니다. 단일 지역 관측이므로 지역별 장애는 구분하지 않습니다.
- TLS 를 중간에서 복호화하는 프록시를 거치는 환경에서는 인증서 만료일이 프록시가 제시한 인증서 기준으로 기록됩니다.
- 원본 검사 결과는 `CHECK_RETENTION_DAYS`(기본 90일) 후 삭제되므로 90일보다 긴 일별 막대는 표시하지 않습니다. 장애 기록은 삭제하지 않습니다.
