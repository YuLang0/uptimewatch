# UptimeWatch 프롬프트 모음

이 문서는 AI 코딩 도우미(Claude 등)에게 그대로 붙여 넣어 쓰는 프롬프트입니다.

| 상황 | 사용할 프롬프트 |
|---|---|
| 같은 서비스를 처음부터 다시 만들 때 | [1. 마스터 프롬프트](#1-마스터-프롬프트-처음부터-만들기) |
| 이 코드(uptimewatch.zip)를 이어서 고치거나 기능을 추가할 때 | [2. 후속 작업 프롬프트](#2-후속-작업-프롬프트-기존-코드에서-이어서) + 작업 내용 |
| 어떤 기능을 더할지 고를 때 | [3. 기능 추가 예시](#3-기능-추가-프롬프트-예시) |

`[대괄호]` 부분은 상황에 맞게 바꿔 쓰세요.

---

## 1. 마스터 프롬프트 (처음부터 만들기)

````text
너는 SaaS 플랫폼과 서버 모니터링 서비스를 개발하는 시니어 풀스택 엔지니어야.
내가 관리하는 웹사이트의 상태를 주기적으로 확인하고 장애 발생 시 알림을 보내는 "UptimeWatch"를 만들어줘.
결과물은 바로 배포할 수 있는 전체 코드, README, 테스트 결과까지야.

# 1. 목표
실제 HTTP/HTTPS 요청으로 웹사이트의 응답 상태, 응답 시간, 가동률, 장애 이력을 기록하는 모니터링 플랫폼.

# 2. 기술 스택 (고정)
- 프론트엔드: React 18 + TypeScript, Tailwind CSS, TanStack Query, Recharts, Vite
- 백엔드: FastAPI, SQLAlchemy 2(async) + asyncpg, Alembic, HTTPX(+httpcore)
- 작업자: APScheduler(AsyncIO). 단, 검사 일정 자체는 DB(monitors.next_check_at)에 저장
- DB: PostgreSQL 16 / 배포: Docker Compose / 테스트: Pytest, Vitest, Playwright
- UI 언어: 한국어. 시간대 기본값 Asia/Seoul

# 3. 핵심 기능
## 모니터링 대상
URL, 이름, 설명, 확인 주기(최소 60초), 타임아웃(1~30초), 기대 상태 코드("200-299,301" 형식),
GET/HEAD, 리다이렉트 추적 여부, 연속 실패 기준, 복구 기준, 활성화/일시 정지, 수정·삭제,
"지금 검사"(쿨다운 적용, API는 next_check_at만 당기고 실제 요청은 작업자가 수행).

## 웹사이트 검사
상태 코드, 응답 시간(DNS·연결·TLS·리다이렉트·본문 상한까지 포함), 오류 분류
(timeout / dns / connection / tls / status / blocked / redirect / protocol / internal),
TLS 인증서 만료일, 마지막 검사 시각, 연속 실패 횟수.
결과는 up / down / error(측정 불가: 검사기 내부 오류) 세 가지로 저장.

## 장애 판정 (상태 머신)
- down 이 failure_threshold 회 연속 → 장애 생성. 시작 시각 = 연속 실패의 첫 실패, 판정 시각 = 기준 도달 시각
- 기준 미만의 실패 = "불안정"(일시적 실패)으로만 표시하고 장애·알림 없음
- up 이 recovery_threshold 회 연속 → 복구. 복구 시각 = 연속 성공의 첫 성공. 지속 시간 기록
- error(측정 불가)는 연속 카운터와 장애 상태를 바꾸지 않음
- 모니터당 진행 중 장애는 1개(부분 유니크 인덱스). 장애 기록은 삭제하지 않고 보관

## 가동률 (반드시 이 정의를 따를 것)
- 가동률 = up 수 / (up 수 + down 수). 관측한 결과만 사용
- 검사 공백(작업자 중단, 일시 정지)과 측정 불가는 정상으로 간주하지 않음
- 관측이 하나도 없으면 null("데이터 없음")이고, 100%로 표시하지 않음
- 측정 커버리지 = 관측 수 / (관측 가능 기간 ÷ 주기)를 함께 제공
- 화면의 백분율은 내림 처리(99.999%를 100%로 반올림하지 않음)
- 응답 시간 통계는 HTTP 응답을 받은 검사만 사용
- 24시간 / 7일 / 30일 가동률, 평균·최대·최소·p95, 장애 횟수, 누적 중단 시간,
  기간별 응답 시간 그래프(30일은 날짜별), 90일 일별 가동률 막대(데이터 없는 날은 회색)

## 알림
- 대시보드 알림(읽음 처리), 이메일(SMTP, aiosmtplib)
- 장애·복구 알림은 상태 전이 때 1회만(dedupe_key 유니크 제약)
- 같은 모니터·같은 종류 이메일은 N분 안에 재발송 금지(suppressed 기록), 사용자별 시간당 발송 한도
- 장애 지속 재알림(선택), TLS 만료 임박 경고(인증서당 1회)
- 이메일은 발송 기록(outbox)을 먼저 저장한 뒤 작업자가 발송. 실패하면 1분·5분 뒤 재시도하고,
  3회 실패하면 failed 와 오류를 기록
- 테스트 알림 버튼
- SMTP_HOST/SMTP_FROM 이 없으면 "미연동"으로 표시하고 발송 기록에도 skipped(미연동)로 남김.
  설정 화면에 필요한 환경변수 안내를 표시

## 상태 페이지
- 관리자가 고른 모니터와 공개 항목(가동률 / 응답 시간 / 최근 30일 장애)만 표시. 공개 이름 사용
- 공개 API 응답은 허용 목록 방식으로 직접 구성: URL·호스트·IP·오류 메시지·상태 코드·내부 ID·임계값·TLS 정보를 넣지 않음
- 공개 라우트(/status/:slug, /api/public/*)와 관리자 라우트를 분리. 미게시 페이지는 404

# 4. 보안 (필수)
## SSRF
1. URL 정책: http/https 만, user:pass@ 금지, 허용 포트(80,443,8080,8443)만, 단일 라벨 호스트 금지,
   localhost·*.local·*.internal·metadata.google.internal·host.docker.internal 금지,
   127.1·2130706433·0x7f.0x0.0x0.0x1 같은 비표준 숫자 IP 표기 금지, 2048자 제한
2. 주소 정책: DNS 결과의 모든 주소가 공인 주소여야 함(하나라도 내부면 차단). 루프백·사설·CGNAT·링크로컬·
   메타데이터(169.254.169.254, fd00:ec2::254)·멀티캐스트·예약·문서용, ::ffff:/NAT64/6to4/Teredo 에 내장된 IPv4 까지 검사
3. DNS 재바인딩 방지: httpcore 네트워크 백엔드를 교체해 "연결 직전 해석 → 검증 → 검증한 그 IP로 직접 연결".
   TLS SNI·인증서 검증은 원래 호스트명으로
4. 리다이렉트는 직접 추적하며 홉마다 1~3을 다시 적용(최대 5회)
5. 등록할 때와 검사할 때 모두 검증. 테스트용 사설망 예외(CHECK_ALLOWED_CIDRS)는 기본값을 비워 둠
## 요청 제한
GET/HEAD 만, 고정 헤더만(사용자 정의 헤더·인증정보 미지원), 응답 본문은 1MB 까지만 읽고 저장하지 않음,
응답 헤더 미저장, 전체 검사 시간 상한, 전역 동시성 제한, 호스트별 분당 제한(초과분은 건너뛰지 않고 연기),
사용자당 모니터 수 제한
## 인증
- Argon2id 해시
- 서버 측 세션: 토큰은 HttpOnly·SameSite=Lax 쿠키로, DB 에는 SHA-256 해시만 저장
- CSRF: HMAC 파생 토큰을 X-CSRF-Token 헤더로 + 상태 변경 요청의 Origin 검사
- 다른 사용자의 리소스는 404. 로그인·가입·공개 페이지·테스트 알림에 요청 제한
## 비밀정보
SMTP 비밀번호·SECRET_KEY 는 환경변수로만 받음. DB·로그에 저장하지 않음
## 헤더
CSP(script-src 'self', 인라인 스크립트 없음), X-Frame-Options DENY, nosniff, API 응답 Cache-Control: no-store

# 5. 작업자·재시작
- SELECT … FOR UPDATE SKIP LOCKED 로 대상을 선점(작업자를 여러 개 띄워도 중복 검사 없음)
- 재시작하면 밀린 검사를 30초 구간에 분산해 다시 예약
- 하트비트를 기록하고, 60초 이상 끊기면 대시보드에 경고 표시
- SIGTERM 을 받으면 진행 중 검사를 마무리하고 종료
- 보관 기간이 지난 검사 결과(기본 90일)와 만료 세션 정리

# 6. UI
- UptimeRobot 스타일: 상태 카드, 24시간 상태 띠, 90일 막대, 응답 시간 그래프(표로 보기 포함), 장애 타임라인
- 다크 모드(시스템 설정 + 수동 전환, 깜빡임 없이)
- 모바일 반응형(하단 탭)
- 상태는 색만으로 나타내지 말고 아이콘과 텍스트를 함께 표시
- 측정 공백은 그래프에서 선을 끊어 표시하고, 고립된 점은 마커로 표시

# 7. 배포
- Docker Compose: db(internal 네트워크 전용), migrate(1회), api, worker, web(nginx: SPA + /api 프록시 + limit_req), caddy(HTTPS, 선택 profile)
- pgdata 볼륨, restart: unless-stopped, 헬스체크(작업자는 하트비트 기반)
- nginx 는 resolver 127.0.0.11 + 변수 proxy_pass 로 api IP 가 바뀌어도 따라가게
- X-Forwarded-For 는 신뢰한 프록시 값만 사용
- .env.example, 한 번에 실행하는 scripts/setup.sh(.env 자동 생성), backup.sh / restore.sh(pg_dump -Fc)
- 사내 프록시 CA 를 빌드 시크릿으로 선택 주입(EXTRA_CA_FILE)

# 8. 구현 순서
1) DB 설계 → 2) 사이트 등록·관리 API → 3) 주기적 HTTP 검사 → 4) 검사 결과 저장 → 5) 장애 판정
→ 6) 알림 → 7) 통계 대시보드 → 8) 공개 상태 페이지 → 9) 보안·테스트 → 10) Docker 배포

# 9. 테스트 (실제 외부 사이트에 부하를 주지 말 것)
- 로컬 모의 HTTP(S) 서버(trustme 인증서), 모의 SMTP(aiosmtpd), 주입 가능한 가짜 DNS 리졸버를 사용
- 반드시 포함: 200, 500, 타임아웃, DNS 오류, 연결 거부, 일시적 장애와 연속 장애 구분, 복구 감지,
  중복 알림 방지(flapping 포함), 가동률 계산(공백·측정 불가 제외, 데이터 없음 = null),
  SSRF(표기 변형, IPv6 내장, 메타데이터, DNS 재바인딩, IP 고정, 리다이렉트), 인증·CSRF·사용자 분리(404),
  공개 페이지 정보 비노출, TLS 만료·호스트 불일치, 이메일 성공·실패·재시도, 재시작 후 재개, 작업자 2개 동시 실행
- Playwright E2E: 등록 → 정상 → 1회 실패(불안정) → 2회(장애) → 복구 → 알림 각 1건,
  SSRF 입력 거부, 공개 페이지 비노출, 사용자 분리, 이메일 미연동 표시, 다크 모드, 모바일
- 마지막에 Docker Compose 로 실제로 띄워서 정기 검사, 재시작 후 재개, 데이터 보존, 백업·복원을 확인

# 10. 완료 기준
실제 웹사이트 응답 측정 / 1분 이상 간격의 정기 검사 / 가동률·응답 시간 그래프 / 장애·복구 기록 /
알림 / 공개 상태 페이지 / 사용자별 데이터 분리 / 재시작 후 정상 작동 / 테스트 결과(TEST_RESULTS.md) /
전체 코드와 README(실행·환경변수·SMTP 설정·HTTPS 리버스 프록시·작업자·백업/복원·보안 설계)

외부 메일 계정이 필요한 기능은 환경변수와 설정 가이드를 주고, 실제로 설정하기 전에는 "미연동"으로 표시해줘.
진행하면서 단계마다 테스트를 실행하고, 실패하면 고친 뒤 다음 단계로 넘어가.
````

---

## 2. 후속 작업 프롬프트 (기존 코드에서 이어서)

`uptimewatch.zip` 을 압축 해제한 폴더를 열고, 아래 내용 뒤에 원하는 작업을 적어 보내세요.

````text
첨부한(또는 현재 폴더의) "uptimewatch" 프로젝트를 이어서 작업해줘.
먼저 README.md 와 PROMPT.md 를 읽고 구조를 파악한 뒤 시작해.

## 프로젝트 요약
- backend/ (FastAPI + SQLAlchemy async + Alembic + APScheduler 작업자)
  - app/security/ssrf.py: URL·주소 정책 / app/services/checker.py: IP 고정 연결(SafeNetworkBackend), 리다이렉트 직접 추적
  - app/services/monitoring.py: 장애 판정 상태 머신 / stats.py: 가동률(관측 기반) / notifications.py: 알림·중복 제한·outbox
  - app/worker/runner.py: SKIP LOCKED 디스패치, 재시작 재개, 하트비트
  - tests/: pytest(모의 HTTP/SMTP 서버, FakeResolver). DB 는 uptimewatch_test
- frontend/ (React + TS + Tailwind + TanStack Query + Recharts), e2e/ (Playwright, 실행에 DB uptimewatch_e2e 필요)
- docker-compose.yml, scripts/setup.sh·backup.sh·restore.sh

## 반드시 지킬 규칙
1. SSRF 방어를 약화하지 말 것. 서버가 외부로 요청을 보내는 새 기능(웹훅 등)은 checker 와 같은 정책
   (validate_url + SafeNetworkBackend)을 거치게 할 것
2. 가동률 정의를 유지할 것: 공백·측정 불가를 정상으로 세지 않고, 데이터가 없으면 null
3. 모든 조회는 user_id 로 범위를 한정하고, 다른 사용자의 리소스는 404
4. 공개 API 는 허용 목록 방식으로 응답을 구성하고, 내부 정보(URL·오류·ID)를 넣지 말 것
5. 비밀정보는 환경변수로만 받고, DB·로그·응답에 남기지 말 것
6. DB 스키마를 바꾸면 Alembic 마이그레이션을 추가할 것(자동 생성 후 검토)
7. UI 문구는 한국어로, 상태는 색 + 아이콘 + 텍스트로 표시하고, 다크 모드·모바일까지 확인할 것
8. 테스트는 실제 외부 사이트가 아니라 모의 서버로. 변경마다 테스트를 추가하고,
   마지막에 아래가 모두 통과하는지 확인한 뒤 결과를 보고할 것
   - cd backend && ruff check app tests && pytest -q
   - cd frontend && npx tsc -b && npm test && npx playwright test
9. 기존 코드의 스타일(주석 밀도, 이름 짓기, 한국어 오류 메시지)을 따를 것

## 이번 작업
[여기에 원하는 작업을 구체적으로 적기. 예: "Slack 웹훅 알림 채널을 추가해줘"]
````

---

## 3. 기능 추가 프롬프트 예시

2번 프롬프트의 "이번 작업" 자리에 넣어 쓰세요.

**Slack/웹훅 알림**
```text
알림 채널로 Slack Incoming Webhook 과 일반 웹훅(JSON POST)을 추가해줘.
웹훅 URL 은 SSRF 정책(validate_url + SafeNetworkBackend)을 그대로 적용하고, 리다이렉트는 따라가지 마.
URL 은 비밀정보이므로 DB 에 암호화해 저장(키는 환경변수)하고, 화면에는 끝 4자리만 보여줘.
발송은 기존 outbox(notification_deliveries) 흐름과 재시도·중복 제한을 그대로 쓰고, 채널별 테스트 버튼도 넣어줘.
```

**응답 본문 키워드 검사**
```text
모니터에 "응답 본문에 특정 문자열이 있어야 / 없어야 정상" 조건을 추가해줘.
본문은 기존 상한(1MB) 안에서만 검사하고 저장하지 마. 실패 사유는 error_type="keyword" 로 기록하고,
UI 폼·상세 화면·테스트(모의 서버)까지 반영해줘.
```

**점검(유지보수) 기간**
```text
모니터별 예약 점검 기간을 추가해줘. 점검 중에는 검사를 계속하되 장애·알림을 만들지 말고,
가동률 계산에서는 점검 시간을 분모에서 제외해. 공개 상태 페이지에 "점검 예정/점검 중"을 표시해줘.
```

**2단계 인증(TOTP)**
```text
계정 설정에 TOTP 2단계 인증(QR 등록, 복구 코드 10개)을 추가해줘. 비밀키는 암호화해 저장하고,
로그인 시도 제한을 2단계 코드 입력에도 적용해줘.
```

**가동률 보고서**
```text
모니터별 월간 가동률 보고서(가동률, 장애 목록, 평균 응답 시간, 커버리지)를 CSV 로 내려받는 기능을 추가해줘.
기존 stats.py 의 가동률 정의를 그대로 쓰고, 사용자 범위 검사를 적용해줘.
```
