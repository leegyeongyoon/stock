#!/usr/bin/env python3
"""상태 대시보드 생성 — 수집현황·고도화추세·모델상태를 단일 HTML로. 서버 불필요.

models/optimize_log.json + DB(ohlcv_intraday/orderflow_snapshots/daily_movers) + 모델을 읽어
dashboard.html 생성. 브라우저로 열면 됨. daily_pipeline postmarket이 매일 갱신.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

OUT = Path("dashboard.html")
LOG = Path("models/optimize_log.json")


def db_stats() -> dict:
    try:
        from sqlalchemy import text
        from src.database.connection import get_session
        q = {
            "intraday_bars": "SELECT count(*) FROM ohlcv_intraday WHERE interval='1m'",
            "intraday_days": "SELECT count(DISTINCT datetime::date) FROM ohlcv_intraday WHERE interval='1m'",
            "intraday_codes": "SELECT count(DISTINCT code) FROM ohlcv_intraday WHERE interval='1m'",
            "orderflow": "SELECT count(*) FROM orderflow_snapshots",
            "orderflow_days": "SELECT count(DISTINCT captured_at::date) FROM orderflow_snapshots",
            "movers": "SELECT count(*) FROM daily_movers",
            "mock_fills": "SELECT count(*) FROM mock_forward_fills",
        }
        out = {}
        with get_session() as s:
            for k, sql in q.items():
                try:
                    out[k] = s.execute(text(sql)).scalar() or 0
                except Exception:
                    out[k] = 0
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


def model_stats() -> dict:
    try:
        from src.ml.gate import MLGate
        g = MLGate.load()
        if not g:
            return {}
        return {"threshold": round(g.threshold, 3), "n_features": len(g.feature_names)}
    except Exception:  # noqa: BLE001
        return {}


def card(label, value, sub=""):
    return f'<div class="card"><div class="lbl">{label}</div><div class="val">{value}</div><div class="sub">{sub}</div></div>'


def main():
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    db = db_stats()
    mdl = model_stats()
    last = log[-1] if log else {}
    wr = last.get("oos_winrate", 0) * 100
    exp = last.get("oos_exp", 0)
    days = last.get("days", db.get("intraday_days", 0))

    # 상태 배너
    if not log:
        banner, bcls = "데이터 수집 대기 중 — 아직 고도화 이력 없음", "warn"
    elif exp > 0:
        banner, bcls = f"엣지 비용 넘김! (기대 {exp:+.2f}%) — 검증 진행", "good"
    elif wr >= 40:
        banner, bcls = f"본전 코앞 (승률 {wr:.1f}%, 기대 {exp:+.2f}%) — 호가/데이터 누적 필요", "near"
    else:
        banner, bcls = f"엣지 약함 (승률 {wr:.1f}%) — 데이터 더 필요", "warn"

    # 차트 데이터
    labels = list(range(1, len(log) + 1))
    wr_series = [round(r.get("oos_winrate", 0) * 100, 1) for r in log]
    exp_series = [round(r.get("oos_exp", 0), 2) for r in log]

    top_feats = ", ".join(last.get("top_features", [])[:6]) or "—"
    flow_days = db.get("orderflow_days", 0)

    cards = "".join([
        card("최신 선별 승률", f"{wr:.1f}%", f"손익분기 40%"),
        card("거래당 기대값", f"{exp:+.2f}%", "비용 차감 후"),
        card("학습 데이터", f"{db.get('intraday_days', days)}일", f"{db.get('intraday_bars', 0):,}봉 / {db.get('intraday_codes', 0)}종목"),
        card("호가/체결강도", f"{flow_days}일", f"{db.get('orderflow', 0):,} 스냅샷"),
        card("고도화 횟수", f"{len(log)}회", f"모델 임계 {mdl.get('threshold', '—')}"),
    ])

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>단타 ML 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#0b0e14;color:#e6e6e6}}
.wrap{{max-width:1000px;margin:0 auto;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}}.muted{{color:#8a93a6;font-size:13px}}
.banner{{padding:14px 18px;border-radius:10px;margin:18px 0;font-weight:600}}
.good{{background:#0f3d2e;color:#4ade80}}.near{{background:#3d3a0f;color:#facc15}}.warn{{background:#3d1f1f;color:#f87171}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.card{{background:#141925;border:1px solid #232a3a;border-radius:10px;padding:16px}}
.lbl{{color:#8a93a6;font-size:12px}}.val{{font-size:26px;font-weight:700;margin:4px 0}}.sub{{color:#6b7280;font-size:12px}}
.panel{{background:#141925;border:1px solid #232a3a;border-radius:10px;padding:18px;margin-top:18px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #232a3a}}
th{{color:#8a93a6;font-weight:500}}.feat{{color:#60a5fa}}
</style></head><body><div class="wrap">
<h1>단타 ML 연속학습 대시보드</h1>
<div class="muted">생성 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 5분마다 자동 새로고침</div>
<div class="banner {bcls}">{banner}</div>
<div class="cards">{cards}</div>

<div class="panel"><b>고도화 추세 (OOS 선별 승률 / 거래당 기대값)</b>
<canvas id="ch" height="90"></canvas></div>

<div class="panel"><b>교집합 핵심 조건 (최신 모델 중요도 상위)</b>
<div class="feat" style="margin-top:8px">{top_feats}</div>
<div class="muted" style="margin-top:6px">특징 {mdl.get('n_features','—')}개 / 진입 임계확률 {mdl.get('threshold','—')}</div></div>

<div class="panel"><b>수집 현황</b>
<table><tr><th>항목</th><th>값</th></tr>
<tr><td>1분봉</td><td>{db.get('intraday_days',0)}일 / {db.get('intraday_bars',0):,}봉 / {db.get('intraday_codes',0)}종목</td></tr>
<tr><td>호가·체결강도</td><td>{flow_days}일 / {db.get('orderflow',0):,} 스냅샷</td></tr>
<tr><td>그날 movers</td><td>{db.get('movers',0):,} 행</td></tr>
<tr><td>모의 체결 로그</td><td>{db.get('mock_fills',0):,} 건</td></tr>
</table>{'<div class="muted">DB 오류: '+db['error']+'</div>' if 'error' in db else ''}</div>

<div class="muted" style="margin-top:18px">data: models/optimize_log.json + PostgreSQL · 호가데이터 누적될수록 승률↑ 기대</div>
</div>
<script>
const wr={wr_series}, exp={exp_series}, labels={labels};
new Chart(document.getElementById('ch'),{{type:'line',
 data:{{labels:labels,datasets:[
  {{label:'선별 승률 %',data:wr,borderColor:'#4ade80',yAxisID:'y',tension:.3}},
  {{label:'기대값 %',data:exp,borderColor:'#facc15',yAxisID:'y2',tension:.3}}]}},
 options:{{plugins:{{legend:{{labels:{{color:'#e6e6e6'}}}}}},scales:{{
  x:{{ticks:{{color:'#8a93a6'}}}},
  y:{{position:'left',ticks:{{color:'#4ade80'}},title:{{display:true,text:'승률%',color:'#4ade80'}}}},
  y2:{{position:'right',ticks:{{color:'#facc15'}},grid:{{drawOnChartArea:false}}}}}}}}}});
</script></body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"대시보드 생성: {OUT.resolve()}")
    print(f"열기: open {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
