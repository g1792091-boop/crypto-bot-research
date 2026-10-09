#!/usr/bin/env bash
# Demo lab bot: can it run on this (the rule bot's) server? READ-ONLY: it reads numbers and changes nothing
# (no install, no file written, no service touched).
#
#   sudo bash deploy/demobot/capacity_check.sh
#
# Verdict "같은 서버에 설치해도 됩니다" when: available memory >= 1.5 GB, free disk >= 3 GB on / and on /var/lib, and
# the 1-minute load average < CPUs x 0.7. Otherwise it lists what is short. (The demo lab uses about 500 MB normally
# and up to about 1.2 GB for a few minutes each hour while the ranking runs; hard caps: engine 900 MB and 30% of one
# CPU, hourly ranking 1000 MB and 50% of one CPU, dashboard 300 MB.)
set -u
export LC_ALL=C

NEED_MEM_MB=1536
NEED_DISK_MB=3072
PORT=8090

line() { printf '%s: %s\n' "$1" "$2"; }
mb() { awk -v k="$1" 'BEGIN { printf "%.0f", k / 1024 }'; }

echo "== 데모 랩 설치 전 점검 (읽기만 합니다 / read-only)"
echo

# ---- CPU and load
CPUS="$(nproc 2>/dev/null || echo 1)"
MODEL="$(awk -F': *' '/^model name/ { print $2; exit }' /proc/cpuinfo 2>/dev/null)"
[ -n "$MODEL" ] || MODEL="$(lscpu 2>/dev/null | awk -F': *' '/Model name/ { print $2; exit }')"
read -r L1 L5 L15 _ < /proc/loadavg
line "CPU" "${CPUS}개 (${MODEL:-알 수 없음})"
line "부하 (1/5/15분 평균)" "$L1 / $L5 / $L15"

# ---- memory and swap (MemAvailable: what new programs can use without pushing others out)
MEM_TOTAL_KB="$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)"
MEM_AVAIL_KB="$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)"
SWAP_TOTAL_KB="$(awk '/^SwapTotal:/ { print $2 }' /proc/meminfo)"
SWAP_FREE_KB="$(awk '/^SwapFree:/ { print $2 }' /proc/meminfo)"
MEM_AVAIL_MB="$(mb "${MEM_AVAIL_KB:-0}")"
line "메모리 (쓸 수 있음 / 전체)" "$MEM_AVAIL_MB MB / $(mb "${MEM_TOTAL_KB:-0}") MB"
line "스왑 (남음 / 전체)" "$(mb "${SWAP_FREE_KB:-0}") MB / $(mb "${SWAP_TOTAL_KB:-0}") MB"

# ---- disk
disk_free_mb() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 { printf "%.0f", $4 / 1024 }'; }
disk_fs() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 { print $1 }'; }
ROOT_FREE_MB="$(disk_free_mb /)"
VAR_FREE_MB="$(disk_free_mb /var/lib)"
DISKS="/:${ROOT_FREE_MB:-0}"
if [ "$(disk_fs /)" = "$(disk_fs /var/lib)" ]; then
  line "디스크 남음 / (/var/lib 포함)" "${ROOT_FREE_MB:-?} MB"
else
  line "디스크 남음 /" "${ROOT_FREE_MB:-?} MB"
  line "디스크 남음 /var/lib" "${VAR_FREE_MB:-?} MB"
  DISKS="$DISKS /var/lib:${VAR_FREE_MB:-0}"
fi

# ---- the rule bot's services: memory and CPU now (sampled over 3 seconds)
echo
echo "규칙봇 서비스 (지금 돌고 있는 paperbot-*):"
UNITS="$(systemctl list-units 'paperbot-*' --type=service --state=running --no-legend --plain 2>/dev/null | awk '{ print $1 }')"
if [ -z "$UNITS" ]; then
  echo "  (돌고 있는 paperbot 서비스 없음, 또는 systemctl을 읽지 못함)"
else
  declare -A CPU0
  for u in $UNITS; do CPU0[$u]="$(systemctl show -p CPUUsageNSec --value "$u" 2>/dev/null)"; done
  sleep 3
  TOTAL_MEM=0
  for u in $UNITS; do
    m="$(systemctl show -p MemoryCurrent --value "$u" 2>/dev/null)"
    c1="$(systemctl show -p CPUUsageNSec --value "$u" 2>/dev/null)"
    c0="${CPU0[$u]:-}"
    if [[ "$m" =~ ^[0-9]+$ ]]; then
      mem="$((m / 1048576)) MB"; TOTAL_MEM=$((TOTAL_MEM + m / 1048576))
    else
      mem="알 수 없음"
    fi
    if [[ "$c0" =~ ^[0-9]+$ ]] && [[ "$c1" =~ ^[0-9]+$ ]]; then
      cpu="$(awk -v a="$c0" -v b="$c1" 'BEGIN { printf "%.0f%%", (b - a) / 3e9 * 100 }')"
    else
      cpu="알 수 없음"
    fi
    printf '  %s: 메모리 %s, CPU %s (CPU 1개 기준)\n' "$u" "$mem" "$cpu"
  done
  echo "  합계 메모리 약 ${TOTAL_MEM} MB"
fi

# ---- python, port, Tailscale, firewall
echo
PYV="$(python3 --version 2>/dev/null || echo '없음')"
line "python3" "$PYV"
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY_OK=1; else PY_OK=0; fi
if python3 -c 'import ensurepip, venv' 2>/dev/null; then line "python3-venv" "있음"; VENV_OK=1
else line "python3-venv" "없음 (설치 전에: sudo apt-get install -y python3-venv)"; VENV_OK=0; fi

if command -v ss >/dev/null 2>&1; then
  if [ -z "$(ss -Hltn "sport = :$PORT" 2>/dev/null)" ]; then line "포트 $PORT" "비어 있음"; PORT_OK=1
  else line "포트 $PORT" "이미 쓰는 중: $(ss -Hltnp "sport = :$PORT" 2>/dev/null | awk '{ print $NF }' | head -n 1)"; PORT_OK=0; fi
else
  line "포트 $PORT" "알 수 없음 (ss 없음)"; PORT_OK=1
fi

TS_IP=""
if command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1)"
  if [ -n "$TS_IP" ]; then line "Tailscale" "켜짐 ($TS_IP)"; else line "Tailscale" "설치됨, 꺼져 있거나 로그인 안 됨"; fi
else
  line "Tailscale" "설치 안 됨"
fi
if [ "$(id -u)" -eq 0 ] && command -v ufw >/dev/null 2>&1; then
  UFW="$(ufw status 2>/dev/null)"
  if printf '%s\n' "$UFW" | grep -q '^Status: active'; then
    if printf '%s\n' "$UFW" | grep -Eq '^Anywhere on tailscale0[[:space:]]+ALLOW'; then
      line "방화벽 (ufw)" "켜짐 · Tailscale 연결 허용됨 (8090도 따로 열 필요 없음)"
    else
      line "방화벽 (ufw)" "켜짐 · Tailscale 전체 허용 규칙 없음 (설치 스크립트가 8090만 Tailscale에 엽니다)"
    fi
  else
    line "방화벽 (ufw)" "꺼짐"
  fi
fi
if id demobot >/dev/null 2>&1 || [ -d /opt/demobot ]; then
  line "데모 랩" "이미 설치된 흔적 있음 (/opt/demobot 또는 사용자 demobot)"
fi

# ---- verdict
SHORT=()
if [ "${MEM_AVAIL_MB:-0}" -lt "$NEED_MEM_MB" ]; then
  SHORT+=("메모리: 쓸 수 있는 메모리 ${MEM_AVAIL_MB} MB (1.5 GB = ${NEED_MEM_MB} MB 이상 필요)")
fi
for pair in $DISKS; do
  where="${pair%%:*}"; free="${pair##*:}"
  if [ "${free:-0}" -lt "$NEED_DISK_MB" ]; then
    SHORT+=("디스크: $where 남은 공간 ${free} MB (3 GB = ${NEED_DISK_MB} MB 이상 필요)")
  fi
done
if ! awk -v l="$L1" -v c="$CPUS" 'BEGIN { exit !(l < c * 0.7) }'; then
  SHORT+=("CPU: 1분 평균 부하 $L1 (CPU ${CPUS}개 x 0.7 = $(awk -v c="$CPUS" 'BEGIN { printf "%.1f", c * 0.7 }') 미만이어야 함)")
fi
[ "$PY_OK" -eq 1 ] || SHORT+=("python3 3.10 이상 필요 (지금: $PYV)")

echo
echo "== 판정"
if [ "${#SHORT[@]}" -eq 0 ]; then
  echo "같은 서버에 설치해도 됩니다."
  echo "(데모 랩은 평소 메모리 약 500 MB를 쓰고, 매시 몇 분 동안 순위표를 만들 때 최대 약 1.2 GB까지 씁니다."
  echo " CPU는 엔진이 CPU 1개의 30%, 순위표가 몇 분 동안 50%까지로 묶여 있고, 우선순위는 규칙봇보다 낮습니다.)"
else
  echo "지금은 같은 서버에 설치하지 않는 것이 좋습니다. 모자란 것:"
  for s in "${SHORT[@]}"; do echo "  - $s"; done
  echo "이 화면을 개발자에게 보내 주세요."
fi
NOTES=()
[ "$VENV_OK" -eq 1 ] || NOTES+=("python3-venv가 없습니다: sudo apt-get install -y python3-venv")
[ "$PORT_OK" -eq 1 ] || NOTES+=("포트 $PORT를 이미 다른 프로그램이 씁니다: 개발자에게 알려 주세요")
[ -n "$TS_IP" ] || NOTES+=("Tailscale이 꺼져 있으면 대시보드는 SSH 터널로만 볼 수 있습니다")
if [ "${#NOTES[@]}" -gt 0 ]; then
  echo
  echo "참고:"
  for s in "${NOTES[@]}"; do echo "  - $s"; done
fi
echo
echo "이 점검은 아무것도 바꾸지 않았습니다."
[ "${#SHORT[@]}" -eq 0 ]
