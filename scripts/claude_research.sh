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
너는 한국 코스닥 초단타(스캘프) 시스템의 퀀트 연구 보조다. 데이터는 DB(ohlcv_intraday 1m,
orderflow_snapshots)에 있고 models/optimize_log.json 에 OOS 성과 이력이 누적된다.

★ 핵심 방향(반드시 지켜라):
- OHLC/가격 파생 피처(가격위치·봉모양·모멘텀·거래량비·효율 등)는 선별스윕 + 타깃/손절 그리드 +
  디플레이티드 샤프로 **무엣지 확정**됐다. → 가격/OHLC 변형 피처는 더 제안하지 마라(매일 탈락한다).
- 유일하게 미검증된 레버 = **체결강도(exec_strength) · 잔량비(bid_ask_ratio)의 시간 동역학**.
  orderflow_snapshots(code, captured_at, exec_strength, bid_ask_ratio, current_price, volume)에서
  '흐름'을 캐라: 체결강도의 기울기/가속, 잔량비 변화율, 가격과의 발산(divergence),
  임계(예: 체결강도>120) 돌파 지속시간 등. 봉 단일값이 아니라 '시간에 따른 변화'가 핵심.

오늘 할 일 (전부 읽기 + research/ 에만 쓰기):
1. optimize_log.json 추세(상위선별 승률/기대값 개선되나) 한 줄 점검.
2. orderflow_snapshots 의 exec_strength/bid_ask_ratio 양·분포 확인(NOT NULL 행수·일수).
   아직 너무 얇으면(대부분 NULL/상수) 솔직히 '체결강도 데이터 부족'이라 적고 가격 피처로 도망가지 마라.
3. 체결강도/잔량비 시간 동역학 기반 새 후보 피처 1~2개를 가설과 함께
   research/candidate_features_<날짜>.py 에 파이썬 함수로 초안(docstring에 가설). src/ 수정 금지.
4. 가능하면 .venv/bin/python 으로 직접 구간분석 자가검증(상/하위 25% 승률차 ≥ +3%p?) 후 결과 포함.
5. 짧은 일일 리포트: 추세 / 체결강도 데이터 상태 / 제안 피처+자가검증 / 승격 권고.

엄격한 금지: src/ 수정 금지. git commit/push 금지. 파일 삭제 금지. 실거래/실제 자금 절대 안 건드림.
짧고 집중되게(매일 도니 저렴하게).
EOF

echo "[$(date)] 자율 연구 시작" | tee -a "$LOG"
# --bare 금지: 그 모드는 인증을 ANTHROPIC_API_KEY로만 한정해서 setup-token의
# OAuth 토큰(CLAUDE_CODE_OAUTH_TOKEN)을 무시한다. 구독 토큰을 쓰려면 --bare 빼야 함.
claude -p "$PROMPT" \
  --permission-mode dontAsk \
  --allowedTools "Read,Write(research/**),Edit(research/**),Bash(.venv/bin/python *),Bash(git log *),Bash(git diff *),Bash(git status)" \
  --disallowedTools "Bash(git push *),Bash(git commit *),Bash(git checkout *),Bash(rm *),Edit(src/**),Write(src/**)" \
  --max-turns 12 \
  --output-format text \
  >> "$LOG" 2>&1
EC=$?
echo "[$(date)] 종료 (exit $EC)" | tee -a "$LOG"
exit $EC
