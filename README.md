# 한국 주식 분봉 단타 자동매매 시스템

5분봉 데이터 기반 AI 설계 인트라데이 트레이딩 시스템입니다.

## 개요

462종목 60거래일 5분봉 데이터(~190만건)에서 패턴을 마이닝하고, OpenAI GPT-4o가 설계한 전략을 V2 백테스트 엔진으로 검증하여 최종 6개 수익 전략을 도출했습니다.

## 전략 성과

| # | 전략 | 시간대 | 수익률 | 승률 | 거래수 |
|---|------|--------|--------|------|--------|
| 1 | MorningRSINeutralATR | 9:30-11시 | +20.04% | 48.9% | 188 |
| 2 | LunchRSINeutralATRVolume | 11-13시 | +9.18% | 41.8% | 196 |
| 3 | ModifiedRSINeutralATR | 9-14시 | +10.84% | 44.7% | 217 |
| 4 | AfternoonRSINeutralATR | 13-15시 | +3.87% | 42.2% | 204 |
| 6 | AfternoonRSINeutralATRVolume | 13-14:30시 | +11.46% | 44.6% | 175 |
| 8 | MorningWideRSINeutralATR | 9:30-12시 | +14.24% | 46.1% | 193 |
| | **합계** | | **+69.63%** | | **1,173** |

### 핵심 전략 원리
- **RSI 40-60 중립 필터**: 과매수/과매도 회피, 모든 전략의 핵심
- **ATR 변동성 필터**: 충분한 가격 변동이 있는 구간에서만 진입
- **VWAP 상방 확인**: 일중 상승 추세 종목 선별
- **연속 양봉 확인**: 단기 모멘텀 확인
- **SL 3% / TP 5%**: 손익비 1:1.67, 거래비용 감안 손익분기 승률 39%

## 프로젝트 구조

```
stock/
├── src/
│   ├── strategies/
│   │   ├── data_driven/           # 활성 전략 6개
│   │   │   ├── intraday_strategy_1.py   # 오전 9:30-11시
│   │   │   ├── intraday_strategy_2.py   # 점심 11-13시
│   │   │   ├── intraday_strategy_3.py   # 와이드 9-14시
│   │   │   ├── intraday_strategy_4.py   # 오후 13-15시
│   │   │   ├── intraday_strategy_6.py   # 오후 13-14:30시
│   │   │   └── intraday_strategy_8.py   # 오전 9:30-12시
│   │   └── intraday/
│   │       └── base.py            # IntradayStrategy ABC + numpy 헬퍼
│   ├── backtest/
│   │   ├── intraday_engine.py     # V1 엔진 + 데이터 클래스
│   │   └── intraday_engine_v2.py  # V2 엔진 (~13초/462종목)
│   ├── analysis/                  # OpenAI 분석/최적화 인프라
│   ├── api/                       # 데이터 API
│   ├── database/                  # PostgreSQL 연결
│   └── utils/                     # 로깅 등 유틸리티
├── scripts/
│   ├── run_data_driven_backtest.py    # 백테스트 실행
│   ├── optimize_round3.py             # Round 3 최적화
│   ├── optimize_round4.py               # Round 4 GPT 최적화
│   ├── optimize_with_ai_rounds_v2.py  # AI 라운드 최적화
│   ├── analyze_intraday_patterns.py   # 패턴 마이닝
│   └── fetch_top_stocks_data.py       # 데이터 수집
├── reports/                       # 분석/백테스트 리포트 (JSON)
├── docs/                          # 문서
│   ├── INTRADAY_STRATEGIES.md     # 전략 상세 문서
│   └── OPTIMIZATION_HISTORY.md    # 최적화 이력
├── database/                      # DB 덤프
└── tests/                         # 테스트 코드
```

## 설치 및 실행

### 요구사항
- Python 3.11+
- PostgreSQL 15+

### 설치
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 DB 접속 정보 및 OPENAI_API_KEY 설정
```

### 백테스트 실행
```bash
source .venv/bin/activate
python scripts/run_data_driven_backtest.py
```

### 최적화 실행
```bash
# 파라미터 그리드서치 + 시간변형 최적화
python scripts/optimize_round3.py

# Round 4 GPT 최적화 (수익률+승률 동시 개선)
python scripts/optimize_round4.py

# AI 기반 라운드 최적화
python scripts/optimize_with_ai_rounds_v2.py
```

## 문서

- [전략 상세 문서](docs/INTRADAY_STRATEGIES.md): 각 전략의 진입/청산 조건, 파라미터, 성과, 최적화 이력
- [최적화 이력](docs/OPTIMIZATION_HISTORY.md): 전체 최적화 과정 기록

## 라이선스

Private - All rights reserved
