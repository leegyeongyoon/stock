#!/usr/bin/env bash
# 자율 연구 에이전트 — 매일 장 끝나고 한 번 Claude가 데이터 분석 + 새 피처 제안.
#
# 안전: src/ 수정 금지, git push/commit/rm 금지, research/에만 쓰기. 사람이 리뷰 후 승격.
# 인증: 1회 `claude setup-token` → 토큰을 ~/.config/claude_research.env 에 저장:
#   echo 'export CLAUDE_CODE_OAUTH_TOKEN=...토큰...' > ~/.config/claude_research.env && chmod 600 ~/.config/claude_research.env
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
mkdir -p logs research
LOG="logs/research.log"

# 토큰 로드
[ -f "$HOME/.config/claude_research.env" ] && source "$HOME/.config/claude_research.env"
if ! command -v claude >/dev/null 2>&1; then
  echo "[$(date)] claude CLI 없음 — 설치/PATH 확인" | tee -a "$LOG"; exit 1
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "[$(date)] 인증 토큰 없음 — claude setup-token 후 ~/.config/claude_research.env 설정" | tee -a "$LOG"; exit 1
fi

read -r -d '' PROMPT <<'EOF'
너는 한국 코스닥 초단타(스캘프) 시스템의 퀀트 연구 보조다. 오늘 데이터가 DB(ohlcv_intraday 1m,
orderflow_snapshots)에 수집됐고 models/optimize_log.json 에 OOS 성과 이력이 누적된다.

오늘 할 일 (전부 읽기 + research/ 에만 쓰기):
1. models/optimize_log.json 을 읽어 최근 회차들의 상위선별 승률/기대값 추세를 본다(개선되나?).
2. 최신 데이터로 패턴 분석을 돌려 뭐가 먹히는지 확인:
   .venv/bin/python scripts/ml_edge_full_yf.py --cache /tmp/kis_today_1m.pkl
   (필요시 scripts/mine_intraday_patterns_yf.py 도) — 상위 중요 특징(교집합)을 메모.
3. 엣지를 올릴 만한 새 후보 피처 1~2개를 가설과 함께 제안하고, research/candidate_features_<날짜>.py
   에 작은 파이썬 함수로 초안 작성(docstring에 가설 설명). src/ 는 절대 수정하지 마라.
4. 마지막 응답에 짧은 일일 리포트: 추세 / 뭐가 먹히나 / 제안 피처 / 사람이 src/ml/feature_builder.py 로
   승격할지 명확한 권고.

엄격한 금지: src/ 수정 금지. git commit/push 금지. 파일 삭제 금지. 실거래/실제 자금 절대 안 건드림.
짧고 집중되게(매일 도니 저렴하게).
EOF

echo "[$(date)] 자율 연구 시작" | tee -a "$LOG"
claude --bare -p "$PROMPT" \
  --permission-mode dontAsk \
  --allowedTools "Read,Write(research/**),Edit(research/**),Bash(.venv/bin/python scripts/ml_edge_full_yf.py *),Bash(.venv/bin/python scripts/mine_intraday_patterns_yf.py *),Bash(git log *),Bash(git diff *),Bash(git status)" \
  --disallowedTools "Bash(git push *),Bash(git commit *),Bash(git checkout *),Bash(rm *),Edit(src/**),Write(src/**)" \
  --max-turns 12 \
  --output-format text \
  >> "$LOG" 2>&1
EC=$?
echo "[$(date)] 종료 (exit $EC)" | tee -a "$LOG"
exit $EC
