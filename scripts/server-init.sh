#!/usr/bin/env bash
# 새 Ubuntu 서버(Oracle Cloud Always Free 등) 초기 설정 — 한 번만 실행
#   sudo ./scripts/server-init.sh
# 하는 일: ① 서버 내부 방화벽에서 80/443 허용(Oracle 이미지는 기본 차단)  ② 메모리 2GB 미만이면 스왑 2GB 추가
#          ③ Docker 설치·부팅 시 자동 시작  ④ 현재 사용자를 docker 그룹에 추가
set -euo pipefail

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "sudo 로 실행하세요: sudo ./scripts/server-init.sh"; exit 1; }
TARGET_USER="${SUDO_USER:-ubuntu}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ① 방화벽 — Docker 설치 전에 처리해야 Docker 규칙이 rules.v4 에 섞여 저장되지 않습니다.
say "1/4 방화벽: TCP 80·443, UDP 443 허용"
RULES=/etc/iptables/rules.v4
TCP_RULE="-A INPUT -p tcp -m state --state NEW -m multiport --dports 80,443 -j ACCEPT"
UDP_RULE="-A INPUT -p udp -m state --state NEW -m udp --dport 443 -j ACCEPT"
if [ -f "$RULES" ] && grep -qE '^-A INPUT -j REJECT' "$RULES"; then
  # Oracle Ubuntu 이미지: SSH(22) 외 모든 입력을 REJECT 하는 규칙 앞에 허용 규칙을 넣고 파일에 저장(재부팅 후 유지)
  grep -qF -- "$TCP_RULE" "$RULES" || sed -i "/^-A INPUT -j REJECT/i $TCP_RULE" "$RULES"
  grep -qF -- "$UDP_RULE" "$RULES" || sed -i "/^-A INPUT -j REJECT/i $UDP_RULE" "$RULES"
  # 지금 바로 적용
  iptables -C INPUT -p tcp -m state --state NEW -m multiport --dports 80,443 -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p tcp -m state --state NEW -m multiport --dports 80,443 -j ACCEPT
  iptables -C INPUT -p udp -m state --state NEW -m udp --dport 443 -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p udp -m state --state NEW -m udp --dport 443 -j ACCEPT
  echo "   → $RULES 에 저장했습니다."
elif command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
  echo "   → ufw 규칙을 추가했습니다."
else
  echo "   → 서버 내부 방화벽 변경이 필요 없습니다."
fi
echo "   ※ 클라우드 콘솔의 방화벽(Oracle: 보안 목록 Security List)에서도 80·443 을 열어야 합니다."

# ② 스왑
say "2/4 메모리 확인"
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 2000000 ] && [ -z "$(swapon --show --noheadings)" ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "   → 메모리 $((mem_kb / 1024))MB: 이미지 빌드를 위해 스왑 2GB 를 추가했습니다."
else
  echo "   → 메모리 $((mem_kb / 1024))MB: 스왑 추가 불필요"
fi

# ③ Docker
say "3/4 Docker 설치"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "   → 이미 설치됨: $(docker --version)"
else
  apt-get update -qq && apt-get install -y -qq ca-certificates curl git >/dev/null
  curl -fsSL https://get.docker.com | sh   # Docker 공식 설치 스크립트 (Engine + Compose 플러그인)
fi
systemctl enable --now docker >/dev/null 2>&1   # 서버 재부팅 시 자동 시작 → 컨테이너도 restart 정책으로 복구

# ④ 권한
say "4/4 '$TARGET_USER' 사용자를 docker 그룹에 추가"
usermod -aG docker "$TARGET_USER"

say "서버 준비 완료"
echo "   다음 단계: 'exit' 로 접속을 끊고 다시 SSH 접속한 뒤(그룹 권한 반영)"
echo "     cd $REPO_DIR && ./scripts/setup.sh --domain <내도메인>"
