#!/usr/bin/env bash
# 연속학습 일일 파이프라인 — cron으로 매 거래일 자동 실행.
#
#   intraday   : 09:00 — 그날 movers 선정 + 호가/체결강도 장중 수집(15:30까지 블로킹)
#   postmarket : 15:45 — 오늘 1분봉 수집 + ML 고도화(auto_optimize) → 최적 모델 갱신
#
# crontab -e 에 (평일만):
#   0  9  * * 1-5  cd /Users/igyeong-yun/stock && scripts/daily_pipeline.sh intraday   >> logs/collect.log 2>&1
#   45 15 * * 1-5  cd /Users/igyeong-yun/stock && scripts/daily_pipeline.sh postmarket >> logs/optimize.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p logs models

MODE="${1:-postmarket}"
echo "[$(date)] daily_pipeline: $MODE"

case "$MODE" in
  intraday)
    $PY scripts/collect_daily_movers.py
    # caffeinate -i: 수집이 도는 동안 시스템 sleep 방지 (화면 잠금은 원래 무관).
    # 09:00 시작되면 collect_orderflow가 끝나는 15:30까지 맥이 안 잔다.
    caffeinate -i -- $PY scripts/collect_orderflow.py --interval 10
    ;;
  postmarket)
    $PY scripts/fetch_kis_today.py 80                # 오늘 movers 1분봉 (캐시 + 추후 DB적재 확장)
    # DB에 분봉/호가가 쌓이면 날짜범위로 고도화 (최근 30일 누적 학습)
    START=$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d '30 days ago' +%Y-%m-%d)
    END=$(date +%Y-%m-%d)
    $PY scripts/auto_optimize.py --start "$START" --end "$END" --target 1.5 --stop 1.0 --cost 0.5 || \
      $PY scripts/auto_optimize.py --cache /tmp/kis_today_1m.pkl --target 1.5 --stop 1.0 --cost 0.5
    $PY scripts/build_dashboard.py   # 대시보드 갱신
    ;;
  *)
    echo "사용법: daily_pipeline.sh [intraday|postmarket]"; exit 1 ;;
esac
echo "[$(date)] 완료"
