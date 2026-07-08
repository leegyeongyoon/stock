#!/usr/bin/env bash
# 체결강도(exec_strength) 봉당 커버리지 점검 — 실전 WS가 종일 데이터를 채우는지.
# launchd(com.gylee.stock.exec-strength-check)로 매 거래일 장마감 후 실행. 결과는 로그 + macOS 알림.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p logs
LOG="logs/exec_strength_check.log"
TODAY="$(date +%Y-%m-%d)"

ROW="$(docker exec stock-pg psql -U stock -d stock_trading -t -A -c \
  "select count(*)||'|'||count(*) filter (where exec_strength is not null) \
   from orderflow_snapshots where captured_at::date='${TODAY}';" \
  2>/dev/null | tr -d '[:space:]')"
TOT="${ROW%%|*}"; ES="${ROW##*|}"
TOT="${TOT:-0}"; ES="${ES:-0}"

if [[ "$TOT" =~ ^[0-9]+$ ]] && [ "$TOT" -gt 0 ]; then
  PCT=$(( 100 * ES / TOT ))
  if   [ "$PCT" -ge 70 ]; then ICON="✅"; NOTE="정상(실전)"
  elif [ "$PCT" -ge 30 ]; then ICON="🟡"; NOTE="낮음 — WS 안정성 확인"
  else                         ICON="⚠️"; NOTE="비정상 — WS 점검 필요"
  fi
  MSG="${ICON} ${TODAY} 체결강도 커버리지 ${PCT}% (${ES}/${TOT}행) — ${NOTE}"
else
  MSG="⚠️ ${TODAY} 수집 0행 — 수집기/네트워크 점검 필요"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${MSG}" >> "$LOG"
osascript -e "display notification \"${MSG}\" with title \"stock 체결강도 커버리지\"" 2>/dev/null || true
echo "$MSG"
