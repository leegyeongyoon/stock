# 키움 API 기반 한국 주식 자동매매 시스템

## 프로젝트 개요

**목표**: 키움증권 API를 활용한 코스피/코스닥 전종목 대상 자동매매 시스템
- 일 수익률: 3-4% 목표
- 월 수익률: 30% 목표
- 10개 트레이딩 전략 구현
- 전종목 백테스트 시스템

## 기술 스택

- **언어**: Python 3.11+
- **데이터 수집 (Mac/Linux)**:
  - `pykrx`: 한국거래소 공식 데이터
  - `FinanceDataReader`: 다양한 금융 데이터
- **데이터 수집 (Windows)**: `pykiwoom` (실시간 매매 시)
- **데이터베이스**: PostgreSQL + SQLAlchemy ORM + Alembic (마이그레이션)
- **백테스트**: 자체 엔진 (vectorbt 참고)
- **기술적 분석**: pandas-ta, ta-lib (선택)
- **시각화**: plotly
- **스케줄링**: APScheduler

## 사용자 환경

- **운영체제**: Mac/Linux
- **키움 계좌**: 계좌 보유 (API 신청 필요)
- **테스트 방식**: 모의투자 우선
- **전략**: 10개 전략 전체 구현

## 중요 제약 사항 및 해결책

> **키움 API 제약**
> - Windows 환경 필수 (COM 기반)
> - 32bit Python 필수
> - 키움증권 계좌 및 API 신청 필요
> - 초당 요청 제한 있음 (TR 제한)

### Mac/Linux 환경 해결책

**Phase A: 백테스트 개발 (Mac에서 가능)**
- `pykrx`: 한국거래소 데이터 무료 수집
- `FinanceDataReader`: 국내주식 데이터
- 키움 API 없이 백테스트 엔진 개발 가능

**Phase B: 실시간 매매 (Windows 필요)**
1. **옵션 1**: Parallels/VirtualBox로 Windows VM
2. **옵션 2**: AWS/GCP Windows 인스턴스
3. **옵션 3**: Windows PC 별도 구비

> **수익률 관련 현실적 기대치**
> - 일 3-4%는 매우 공격적인 목표
> - 리스크 관리 없이는 큰 손실 가능
> - 백테스트 수익 ≠ 실제 수익 (슬리피지, 체결 지연)

---

## Phase 1: 프로젝트 기반 구축

### 1.1 프로젝트 구조
```
stock/
├── src/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py          # 환경설정
│   │   └── constants.py         # 상수 정의
│   ├── api/
│   │   ├── __init__.py
│   │   ├── kiwoom_api.py        # 키움 API 래퍼
│   │   ├── data_fetcher.py      # 데이터 수집
│   │   └── order_manager.py     # 주문 관리
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py        # PostgreSQL 연결
│   │   ├── models.py            # SQLAlchemy 모델
│   │   ├── repositories.py      # 데이터 접근 계층
│   │   └── migrations/          # DB 마이그레이션
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # 전략 베이스 클래스
│   │   ├── momentum/            # 모멘텀 전략들
│   │   ├── mean_reversion/      # 평균회귀 전략들
│   │   ├── breakout/            # 돌파 전략들
│   │   └── ml/                  # ML 기반 전략들
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py            # 백테스트 엔진
│   │   ├── metrics.py           # 성과 지표
│   │   └── reporter.py          # 리포트 생성
│   ├── trading/
│   │   ├── __init__.py
│   │   ├── executor.py          # 주문 실행
│   │   ├── portfolio.py         # 포트폴리오 관리
│   │   └── risk_manager.py      # 리스크 관리
│   └── utils/
│       ├── __init__.py
│       ├── logger.py            # 로깅
│       ├── validators.py        # 입력 검증
│       └── helpers.py           # 유틸리티 함수
├── tests/
│   ├── __init__.py
│   ├── test_strategies/
│   ├── test_backtest/
│   └── test_api/
├── reports/                     # 백테스트 리포트 (HTML/PDF)
├── logs/
├── requirements.txt
├── pyproject.toml
└── main.py
```

### 1.2 설정 파일
- `requirements.txt`: 의존성 패키지
- `pyproject.toml`: 프로젝트 메타데이터
- `.env`: 환경 변수 (API 키, 계좌 정보)

---

## Phase 2: 키움 API 연동

### 2.1 데이터 수집기 (pykrx 기반 - Mac/Linux 호환)
```python
class DataFetcher:
    - get_kospi_tickers(): 코스피 전종목 코드
    - get_kosdaq_tickers(): 코스닥 전종목 코드
    - get_ohlcv(ticker, start, end): 일봉 데이터
    - get_market_cap(ticker): 시가총액
    - get_fundamental(ticker): 재무 데이터
    - get_investor_trading(ticker): 투자자별 거래
```

### 2.2 수집 데이터
- 코스피/코스닥 전종목 리스트 (약 2,400종목)
- 일봉 데이터 (최소 3년, 2022-2025)
- 투자자별 매매동향 (기관, 외인, 개인)
- 시가총액, 거래대금
- (추후 키움) 분봉 데이터, 실시간 체결

### 2.3 키움 API 래퍼 (Windows 전용 - 추후)
```python
class KiwoomAPI:
    - connect(): 로그인
    - get_minute_ohlcv(): 분봉 데이터
    - send_order(): 주문 전송
    - get_balance(): 잔고 조회
```

### 2.4 PostgreSQL 데이터베이스 스키마

```sql
-- 종목 정보
CREATE TABLE stocks (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    market VARCHAR(10) NOT NULL,  -- KOSPI/KOSDAQ
    sector VARCHAR(50),
    market_cap BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 일봉 데이터 (파티셔닝 적용)
CREATE TABLE ohlcv_daily (
    id SERIAL,
    code VARCHAR(10) REFERENCES stocks(code),
    date DATE NOT NULL,
    open INTEGER NOT NULL,
    high INTEGER NOT NULL,
    low INTEGER NOT NULL,
    close INTEGER NOT NULL,
    volume BIGINT NOT NULL,
    value BIGINT,              -- 거래대금
    change_rate DECIMAL(10,4),
    PRIMARY KEY (code, date)
);
CREATE INDEX idx_ohlcv_daily_date ON ohlcv_daily(date);

-- 투자자별 매매동향
CREATE TABLE investor_trading (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) REFERENCES stocks(code),
    date DATE NOT NULL,
    institution_buy BIGINT,    -- 기관 매수
    institution_sell BIGINT,   -- 기관 매도
    foreign_buy BIGINT,        -- 외인 매수
    foreign_sell BIGINT,       -- 외인 매도
    individual_buy BIGINT,     -- 개인 매수
    individual_sell BIGINT,    -- 개인 매도
    UNIQUE(code, date)
);

-- 백테스트 결과
CREATE TABLE backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    run_date TIMESTAMP DEFAULT NOW(),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_return DECIMAL(10,4),
    cagr DECIMAL(10,4),
    sharpe_ratio DECIMAL(10,4),
    max_drawdown DECIMAL(10,4),
    win_rate DECIMAL(10,4),
    total_trades INTEGER,
    config JSONB                -- 전략 파라미터
);

-- 개별 거래 내역
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    backtest_id INTEGER REFERENCES backtest_results(id),
    code VARCHAR(10) REFERENCES stocks(code),
    strategy_name VARCHAR(50),
    entry_date TIMESTAMP,
    entry_price INTEGER,
    exit_date TIMESTAMP,
    exit_price INTEGER,
    quantity INTEGER,
    pnl INTEGER,
    pnl_rate DECIMAL(10,4),
    is_live BOOLEAN DEFAULT FALSE  -- 실전/백테스트 구분
);

-- 전략 신호 로그
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50),
    code VARCHAR(10),
    signal_type VARCHAR(10),   -- BUY/SELL
    signal_date TIMESTAMP,
    price INTEGER,
    reason TEXT,
    executed BOOLEAN DEFAULT FALSE
);
```

---

## Phase 3: 10가지 트레이딩 전략

### 전략 1: 급등주 포착 (Volume Breakout)
- **원리**: 거래량 급증 + 가격 돌파
- **진입**: 20일 평균 거래량 300% 돌파 + 전일 고가 돌파
- **청산**: 3% 수익 또는 -1.5% 손절

### 전략 2: 갭 상승 매매 (Gap Up Strategy)
- **원리**: 시초가 갭상승 후 추가 상승
- **진입**: 시가 > 전일 종가 * 1.02, 09:05 이후 고가 돌파
- **청산**: 당일 종가 또는 -2% 손절

### 전략 3: VWAP 회귀 전략 (VWAP Reversion)
- **원리**: VWAP 이탈 후 회귀
- **진입**: 가격이 VWAP 대비 -2% 이탈 시 매수
- **청산**: VWAP 도달 또는 -1% 손절

### 전략 4: RSI 과매도 반등 (RSI Oversold Bounce)
- **원리**: 과매도 구간에서 반등
- **진입**: RSI(14) < 30, 양봉 출현
- **청산**: RSI > 50 또는 -2% 손절

### 전략 5: 이동평균 골든크로스 (MA Golden Cross)
- **원리**: 단기 이평선이 장기 이평선 상향돌파
- **진입**: MA(5) > MA(20) 교차 + 거래량 증가
- **청산**: MA(5) < MA(20) 교차 또는 -3% 손절

### 전략 6: 볼린저밴드 수축 돌파 (BB Squeeze Breakout)
- **원리**: 변동성 수축 후 확대
- **진입**: BB 밴드폭 최저점 + 상단 돌파
- **청산**: 중심선 이탈 또는 -2% 손절

### 전략 7: 거래대금 상위 모멘텀 (Top Volume Momentum)
- **원리**: 거래대금 상위 종목 추세 추종
- **진입**: 거래대금 상위 50 + 3일 연속 상승
- **청산**: 음봉 2개 연속 또는 -2% 손절

### 전략 8: 52주 신고가 돌파 (52-Week High Breakout)
- **원리**: 신고가 돌파 시 추가 상승
- **진입**: 52주 신고가 갱신 + 거래량 150% 이상
- **청산**: 5% 수익 또는 -2% 손절

### 전략 9: 기관/외인 수급 추종 (Institutional Flow)
- **원리**: 기관/외인 순매수 종목 추종
- **진입**: 3일 연속 기관+외인 순매수 + 상승
- **청산**: 순매도 전환 또는 -2% 손절

### 전략 10: 섹터 로테이션 (Sector Rotation)
- **원리**: 강세 섹터의 후발주 매수
- **진입**: 섹터 1위 종목 5% 상승 시 2-3위 종목 매수
- **청산**: 섹터 약세 전환 또는 -2% 손절

---

## Phase 4: 백테스트 엔진

### 4.1 백테스트 기능
```python
class BacktestEngine:
    - run(strategy, symbols, start_date, end_date)
    - calculate_metrics()
    - generate_report()

    # 지원 지표
    - Total Return
    - CAGR
    - Sharpe Ratio
    - Max Drawdown
    - Win Rate
    - Profit Factor
    - Average Trade Duration
```

### 4.2 백테스트 리포트
- 전략별 성과 비교
- 종목별 성과
- 주간/월간 성과 집계
- 드로다운 분석
- 거래 상세 내역

### 4.3 전종목 백테스트
- 코스피 약 800종목
- 코스닥 약 1,600종목
- 병렬 처리로 속도 최적화
- 결과 캐싱

---

## Phase 5: 실시간 자동매매

### 5.1 트레이딩 엔진
```python
class TradingEngine:
    - start(): 매매 시작
    - stop(): 매매 중지
    - scan_signals(): 전략별 신호 스캔
    - execute_trade(): 주문 실행
    - monitor_positions(): 포지션 모니터링
```

### 5.2 리스크 관리
- 종목당 최대 투자 비율: 10%
- 일일 최대 손실: -3%
- 동시 보유 종목 수: 최대 10개
- 손절 자동 실행
- 장 종료 30분 전 강제 청산 옵션

### 5.3 주문 관리
- 시장가/지정가 주문
- 분할 매수/매도
- 슬리피지 최소화
- 체결 확인 및 재주문

---

## Phase 6: 모니터링 대시보드

### 6.1 실시간 모니터링
- 현재 포지션
- 일일 손익
- 전략별 성과
- 시스템 상태

### 6.2 알림 시스템
- 텔레그램/카카오톡 연동
- 주문 체결 알림
- 손절/익절 알림
- 시스템 오류 알림

---

## 구현 순서 (Mac/Linux 우선)

### 1단계: Mac에서 백테스트 시스템 구축
| 순서 | 작업 | 설명 |
|------|------|------|
| 1 | 프로젝트 구조 | 폴더 구조, 설정, 의존성 |
| 2 | 데이터 수집 | pykrx로 코스피/코스닥 전종목 데이터 |
| 3 | 전략 구현 | 10가지 트레이딩 전략 |
| 4 | 백테스트 엔진 | 성과 분석, 리포트 생성 |

### 2단계: Windows에서 실시간 매매 (추후)
| 순서 | 작업 | 설명 |
|------|------|------|
| 5 | 키움 API 연동 | Windows VM 또는 별도 PC |
| 6 | 실시간 매매 | 자동 주문 실행 |
| 7 | 모니터링 | 대시보드, 알림 시스템 |

---

## 검증 방법

### 단위 테스트
- 각 전략의 신호 생성 로직
- 주문 관리 로직
- 리스크 관리 로직

### 통합 테스트
- 키움 API 연동 (모의투자)
- 백테스트 전체 파이프라인
- 주문 실행 파이프라인

### 백테스트 검증
1. 각 전략별 3년 백테스트 실행
2. 코스피/코스닥 전종목 대상
3. 주간/월간 성과 리포트 생성
4. 수익률, 샤프 비율, MDD 확인

### 실전 검증
1. 키움 모의투자로 2주 테스트
2. 소액 실전 투자 (100만원)
3. 성과 분석 및 전략 튜닝

---

## 주의사항

1. **법적 이슈**: 자동매매는 합법이나, 시세조종 의심 행위 주의
2. **세금**: 양도소득세 자동 계산 기능 고려
3. **API 제한**: 키움 API TR 제한 준수
4. **슬리피지**: 백테스트와 실제 수익 차이 존재
5. **시스템 안정성**: 장애 대비 및 복구 로직 필수

---

## 다음 단계

1. 프로젝트 구조 생성 및 의존성 설치
2. pykrx로 코스피/코스닥 전종목 데이터 수집
3. 10가지 전략 구현
4. 백테스트 엔진으로 전종목 검증
5. 수익률 높은 전략 선별
6. (추후) Windows 환경에서 키움 API 연동 및 실시간 매매
