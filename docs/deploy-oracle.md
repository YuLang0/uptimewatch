# Oracle Cloud 무료 서버(Always Free)에 배포하기

오라클 클라우드의 **Always Free** 서버에 UptimeWatch 를 올려 24시간 운영하는 방법입니다.
처음이라면 1~2시간(가입 포함), 익숙하면 20분 정도 걸립니다.

```
[가입] → [서버 만들기] → [포트 열기] → [도메인 연결] → [SSH 접속] → [스크립트 2개 실행] → [https://내도메인 접속]
```

> 오라클 콘솔 화면은 자주 바뀝니다. 메뉴 이름이 조금 달라도 같은 위치의 비슷한 항목을 찾으면 됩니다.
> 콘솔은 한국어로도 볼 수 있으며, 아래에 영어 이름을 함께 적었습니다.

---

## 1. 오라클 클라우드 가입

1. https://www.oracle.com/cloud/free/ → **무료로 시작하기(Start for free)**
2. **홈 리전(Home Region)** 은 가입 후 바꿀 수 없습니다. **South Korea Central (Seoul)** 또는 **South Korea North (Chuncheon)** 를 고르세요.
   (무료 ARM 서버는 리전별로 자리가 부족할 때가 있어, 춘천이 더 잘 만들어지는 경우가 많습니다.)
3. 본인 확인용으로 카드 정보를 입력합니다. **무료 한도 안에서는 결제되지 않습니다.** (해외 결제 가능한 카드 필요)

---

## 2. 서버(인스턴스) 만들기

콘솔 왼쪽 위 메뉴 **≡ → 컴퓨트(Compute) → 인스턴스(Instances) → 인스턴스 생성(Create instance)**

| 항목 | 설정 |
|---|---|
| 이름 | `uptimewatch` (아무거나) |
| 이미지(Image) | **Canonical Ubuntu 24.04** (또는 22.04) — *Change image* 에서 선택 |
| 구성(Shape) | *Change shape* → **Ampere** → **VM.Standard.A1.Flex**, **OCPU 1 / 메모리 2GB** 권장 (이유는 7장) |
| 네트워킹 | 새 VCN·공용 서브넷 생성(기본값), **공용 IPv4 주소 지정(Assign a public IPv4 address)** 체크 |
| SSH 키 | **키 쌍 생성(Generate a key pair for me)** → **개인 키 저장(Save private key)** 을 눌러 `.key` 파일을 꼭 받아 두기 |

**생성(Create)** 을 누르고 상태가 **실행 중(Running)** 이 되면, 상세 화면의 **공용 IP 주소(Public IP address)** 를 메모합니다.

- 무료 한도: ARM(A1) 은 계정 전체 합계 **4 OCPU / 24GB** 까지 무료입니다.
- **왜 작게?** 무료 계정에서는 사용률이 낮은 서버가 회수될 수 있는데, ARM 서버는 **메모리 사용률**도 판단 기준입니다.
  UptimeWatch 서버 전체가 메모리를 0.6~0.8GB 정도만 쓰므로, 2GB 서버면 사용률이 기준(20%)을 넉넉히 넘고 12GB 서버면 밑돕니다. (7장 참고)
  종량제로 업그레이드할 계획이면 크기는 자유롭게 정해도 됩니다.
- **"Out of capacity" 오류**가 나면: 다른 가용성 도메인(AD)을 고르거나 몇 시간 뒤 다시 시도하세요.
- ARM 자리가 계속 없으면 **VM.Standard.E2.1.Micro**(AMD, 메모리 1GB, 무료)도 동작합니다(`server-init.sh` 가 스왑 자동 추가).
  다만 이 종류는 메모리가 회수 판단 기준에 들어가지 않아, 무료 계정에서는 회수될 가능성이 더 큽니다.
- 개인 키 파일을 잃어버리면 서버에 접속할 수 없습니다. 안전한 곳에 보관하세요.

---

## 3. 클라우드 방화벽에서 80·443 포트 열기

인스턴스 상세 → **기본 VNIC(Primary VNIC)** 의 **서브넷(Subnet)** 링크 → **보안 목록(Security Lists)** →
**Default Security List for …** → **수신 규칙 추가(Add Ingress Rules)**

| 소스 CIDR | IP 프로토콜 | 대상 포트 범위 |
|---|---|---|
| `0.0.0.0/0` | TCP | `80,443` |
| `0.0.0.0/0` | UDP | `443` (선택, HTTP/3) |

> 오라클은 이 콘솔 방화벽 **외에 서버 안의 방화벽(iptables)도** 기본으로 막혀 있습니다.
> 서버 안쪽은 5단계의 `server-init.sh` 가 열어 줍니다. 두 군데 모두 열려야 접속됩니다.

---

## 4. 도메인 연결

HTTPS 인증서를 자동으로 받으려면 도메인이 필요합니다.

- **도메인이 있다면**: DNS 관리 화면에서 `A` 레코드(예: `status`)를 서버 공용 IP 로 추가 → `status.내도메인.com`
- **없다면 (무료)**: https://www.duckdns.org 에 로그인 → 원하는 이름으로 서브도메인 추가(예: `myuptime`) →
  **current ip** 칸에 서버 공용 IP 입력 → **update ip** → 주소는 `myuptime.duckdns.org`

설정 후 몇 분 뒤 PC 에서 확인: `nslookup myuptime.duckdns.org` → 서버 IP 가 나오면 OK.

---

## 5. 서버에 접속해서 설치

### SSH 접속

**Windows (PowerShell)**
```powershell
# 개인 키 권한을 본인만 읽을 수 있게(처음 한 번). "UNPROTECTED PRIVATE KEY FILE" 오류 방지
# (파일 이름은 실제로 받은 키 파일 이름으로 바꾸세요. 예: ssh-key-2026-10-28.key)
icacls "$HOME\Downloads\ssh-key-2026-10-28.key" /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i "$HOME\Downloads\ssh-key-2026-10-28.key" ubuntu@<공용IP>
```

**Mac / Linux**
```bash
chmod 600 ~/Downloads/ssh-key-2026-10-28.key
ssh -i ~/Downloads/ssh-key-2026-10-28.key ubuntu@<공용IP>
```
처음 접속 시 `Are you sure you want to continue connecting?` → `yes`

### 설치 (서버에서)

```bash
# ① 코드 받기
git clone https://github.com/YuLang0/uptimewatch.git
cd uptimewatch

# ② 서버 초기 설정: 서버 안쪽 방화벽 80·443 열기, (필요 시) 스왑, Docker 설치
sudo ./scripts/server-init.sh

# ③ docker 권한 반영을 위해 접속을 끊었다가 다시 접속
exit
```
```bash
ssh -i <키 파일> ubuntu@<공용IP>
cd uptimewatch

# ④ 실행 (도메인 자리에 4단계에서 만든 주소)
./scripts/setup.sh --domain myuptime.duckdns.org
```

`setup.sh` 가 하는 일: `.env` 생성(DB 비밀번호·보안 키 무작위) → HTTPS 설정 → 이미지 빌드(ARM 서버에서 5~10분) →
전체 서비스 실행 → 인증서 발급 확인. 마지막에 **"완료! 브라우저에서 https://… 에 접속"** 이 나오면 성공입니다.

---

## 6. 처음 접속 후 꼭 할 일

1. 브라우저에서 `https://myuptime.duckdns.org` → **회원가입**(내 계정) → 모니터 등록
2. **다른 사람이 가입하지 못하게 막기** (서버에서):
   ```bash
   cd ~/uptimewatch
   sed -i 's/^ALLOW_REGISTRATION=.*/ALLOW_REGISTRATION=false/' .env && docker compose up -d
   ```
3. (선택) 이메일 알림: `nano .env` 로 `SMTP_*` 를 채운 뒤 `docker compose up -d` → 화면의 **알림 → 설정 → 테스트 알림 보내기**
4. 매일 자동 백업 (서버에서 `crontab -e` 후 맨 아래 줄 추가):
   ```
   10 3 * * * cd /home/ubuntu/uptimewatch && ./scripts/backup.sh >> backups/backup.log 2>&1
   ```
   백업 파일은 서버 안(`~/uptimewatch/backups`)에 쌓입니다. 중요한 데이터라면 가끔 PC 로 내려받아 두세요:
   `scp -i <키 파일> ubuntu@<공용IP>:~/uptimewatch/backups/*.dump .`

---

## 7. ⚠️ 무료 계정의 '유휴 서버 회수' 정책과 무료로 유지하는 법

오라클은 **무료(Free Tier) 계정**의 Always Free 서버가 **7일 동안 아래 조건을 모두** 만족하면 "유휴"로 보고 회수(중지)할 수 있다고 안내합니다.

| 기준 (7일) | 유휴로 보는 조건 | UptimeWatch 에서는 |
|---|---|---|
| CPU 사용률 (95번째 백분위) | 20% 미만 | 1분 주기 검사는 가벼워서 **항상 미만** |
| 네트워크 사용률 | 20% 미만 | **항상 미만** |
| 메모리 사용률 (**ARM A1 서버만**) | 20% 미만 | **서버 크기에 따라 달라짐** ← 여기가 핵심 |

세 조건이 **모두** 맞아야 유휴이므로, ARM 서버에서 **메모리 사용률이 20% 이상**이면 유휴 조건에서 벗어납니다.

### 방법 1 — 서버를 작게 잡기 (추천, 종량제 전환 없음)
실측(모니터 몇 개 기준): 컨테이너 5개(DB·API·작업자·웹·Caddy) 약 200MB + Docker 약 150~200MB
+ 운영체제·오라클 에이전트 약 300~400MB ≈ **0.6~0.8GB**. 모니터와 기록이 늘면 조금씩 늘어납니다.

| A1 메모리 | 예상 사용률 | 무료 계정에서 |
|---|---|---|
| **2GB** | 약 30~40% | ✅ 권장 |
| 3GB | 약 20~27% | 경계선 |
| 4GB 이상 | 20% 미만 | ❌ 유휴로 판단될 수 있음 |

**확인하기** (설치 후 하루쯤 지나서)
- 서버에서: `free | awk '/Mem:/{printf "메모리 사용률 %.0f%%\n", ($2-$7)/$2*100}'`
- 콘솔에서: 인스턴스 상세 → **지표(Metrics)** → *Memory Utilization* 그래프 (오라클이 실제로 보는 값)

이미 큰 서버를 만들었다면 **중지(Stop) → 구성 편집(Edit → Shape) → 메모리 2GB 로 변경 → 시작(Start)** 하면 됩니다.
디스크와 데이터는 그대로 유지됩니다.

### 방법 2 — 서버가 멈추면 바로 알기 (함께 쓰기)
회수되더라도 **삭제가 아니라 중지**이며, 오라클이 보통 미리 이메일로 알립니다. 디스크와 데이터는 남아 있어 콘솔에서
**시작(Start)** 하면 자동으로 다시 동작합니다(Docker 가 부팅 시 시작되고, 작업자가 밀린 검사를 이어서 수행).

문제는 "모니터링 서버 자체가 멈춘 걸 모르는 것"이므로, **다른 무료 모니터링 서비스로 내 UptimeWatch 를 감시**하세요.
- UptimeRobot(무료 50개) 등에 `https://내도메인/api/health` 를 등록 → 서버가 멈추면 이메일로 알림

### 하지 말 것 — 가짜 부하 만들기
CPU 를 일부러 계속 쓰게 하는 스크립트로 기준을 피하는 방법이 커뮤니티에 돌기도 하지만, 회수 정책의 취지를 피해 가는 것이라
권하지 않습니다. 정책이 바뀌거나 계정에 불이익이 생길 수 있고, 공용 자원을 낭비합니다.

### 그래도 불안하다면
- **종량제(Pay As You Go) 업그레이드**: Always Free 자원은 계속 무료이고 이 회수 정책이 적용되지 않습니다
  (콘솔 → 결제 → *Upgrade and Manage Payment*). 업그레이드 후에는 **결제 → 예산(Budgets)** 에서 1달러 예산 알림을 걸어
  실수로 유료 자원을 만들었을 때 바로 알 수 있게 하세요.
- 정책·기준은 바뀔 수 있으니 오라클 공식 문서(*Always Free Resources*)도 확인하세요.

---

## 8. 업데이트 · 관리

```bash
cd ~/uptimewatch
git pull && docker compose up -d --build     # 새 버전 반영(마이그레이션 자동 적용)
docker compose ps                            # 상태
docker compose logs -f api worker            # 로그
docker compose logs caddy                    # HTTPS 인증서 관련 로그
./scripts/backup.sh                          # 즉시 백업
```

`.env` 에 `COMPOSE_PROFILES=https` 가 저장되어 있어 위 명령들은 HTTPS(Caddy)까지 함께 관리합니다.

---

## 9. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| SSH 접속이 안 됨 (`timed out`) | 공용 IP 가 맞는지, 인스턴스가 Running 인지, 보안 목록에 22번(기본 포함)이 있는지 |
| `Permission denied (publickey)` | 사용자 이름이 `ubuntu` 인지, 생성할 때 받은 개인 키 파일을 지정했는지 |
| `setup.sh` 가 "Docker 에 접근할 수 없습니다" | `server-init.sh` 후 `exit` 하고 다시 접속했는지 |
| 브라우저에서 접속이 안 됨 / 시간 초과 | ① 3단계 보안 목록에 TCP 80·443 ② `sudo ./scripts/server-init.sh` 실행 여부 ③ `nslookup 도메인` 결과가 서버 IP 인지 |
| "안전하지 않음" / 인증서 오류 | 도메인이 서버 IP 를 가리킨 뒤 몇 분 기다렸는지, `docker compose logs caddy` 에 오류가 있는지(80번이 막혀 있으면 발급 실패) |
| 로그인 시 "허용되지 않은 출처(Origin)" | 주소창 주소가 `.env` 의 `PUBLIC_BASE_URL`(https://도메인)과 같은지 |
| 대시보드에 "검사 작업자가 응답하지 않습니다" | `docker compose ps` 로 worker 상태 확인, `docker compose logs worker` |
| 빌드 중 멈춤·`Killed` (메모리 2GB 이하 서버) | `free -h` 로 스왑 확인. 없으면 `sudo ./scripts/server-init.sh` 다시 실행 |
| 서버 IP 가 바뀜 | DuckDNS(또는 DNS)의 IP 를 새 값으로 수정. 고정하려면 콘솔에서 **예약된 공용 IP(Reserved Public IP)** 로 변경 |
| 처음부터 다시 설치하고 싶음 | `docker compose down -v` (**모든 데이터 삭제**) → `rm .env` → `./scripts/setup.sh --domain …` |
