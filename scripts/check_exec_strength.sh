#!/usr/bin/env bash
# 체결강도(exec_strength) 수집 건전성 점검 — WS H0STCNT0 연동이 실제로 값을 채우는지.
# launchd(com.gylee.stock.exec-strength-check)로 매주 월 10:00 자동 실행. 결과는 로그 + macOS 알림.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p logs
LOG="logs/exec_strength_check.log"
TODAY="$(date +%Y-%m-%d)"

CNT="$(docker exec stock-pg psql -U stock -d stock_trading -t -A -c \
  "select count(*) from orderflow_snapshots where exec_strength is not null and captured_at::date='${TODAY}';" \
  2>/dev/null | tr -d '[:space:]')"
CNT="${CNT:-0}"

if [[ "$CNT" =~ ^[0-9]+$ ]] && [ "$CNT" -gt 0 ]; then
  MSG="✅ 체결강도 WS 수집 성공 — ${TODAY} exec_strength 채워진 행 ${CNT}개"
else
  MSG="⚠️ 체결강도 0건 (${TODAY}) — 모의서버 WS 틱 미수신, 실전계좌 키 필요 가능성"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${MSG}" >> "$LOG"
osascript -e "display notification \"${MSG}\" with title \"stock 체결강도 점검\"" 2>/dev/null || true
echo "$MSG"
