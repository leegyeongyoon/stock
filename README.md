# 한국 주식 자동매매 시스템

AI 기반 전략 최적화를 통한 한국 주식 자동매매 시스템입니다.

## 개요

이 프로젝트는 10개의 매매 전략을 구현하고, OpenAI GPT-4o를 활용하여 각 전략의 파라미터를 반복적으로 최적화합니다.

## 구현된 전략

| 전략 | 설명 | 최종 수익률 |
|-----|------|-----------|
| **VolumeBreakout** | 거래량 급증 돌파 전략 | 9.79% |
| **GapUp** | 갭상승 매매 전략 | -0.07% |
| **VWAPReversion** | VWAP 회귀 전략 | 4.43% |
| **RSIOversold** | RSI 과매도 반등 전략 | 3.19% |
| **MAGoldenCross** | 이동평균 골든크로스 전략 | 12.94% |
| **BBSqueeze** | 볼린저밴드 스퀴즈 전략 | 10.71% |
| **TopVolumeMomentum** | 거래대금 상위 모멘텀 전략 | 8.46% |
| **High52WeekBreakout** | 52주 신고가 돌파 전략 | -0.66% |
| **InstitutionalFlow** | 기관 수급 추종 전략 | 1.40% |
| **SectorRotation** | 섹터 로테이션 전략 | -2.37% |

**총 수익률: 47.83%** (백테스트 기간: 2022-01-01 ~ 2025-01-31)

## AI 최적화 시스템

### 작동 방식

1. **코드 분석**: GPT-4o가 전략 코드를 분석하고 개선점을 제안
2. **파라미터 검증**: 각 제안을 백테스트로 검증
3. **자동 적용**: 개선이 확인되면 전략 코드에 자동 반영
4. **피드백 루프**: 실패한 시도를 기록하고 다음 반복에 피드백

### 최적화 이력

#### 1차 최적화 (5회 반복)
- 초기: 19.03% → 최종: 42.89%
- 개선: +23.86%

#### 2차 최적화 (10회 반복)
- 초기: 42.89% → 최종: 47.83%
- 개선: +4.94%

**총 개선: +28.80%**

## 프로젝트 구조

```
stock/
├── src/
│   ├── strategies/          # 매매 전략
│   │   ├── momentum/        # 모멘텀 전략들
│   │   ├── mean_reversion/  # 평균회귀 전략들
│   │   └── breakout/        # 돌파 전략들
│   ├── backtest/            # 백테스트 엔진
│   ├── analysis/            # AI 분석 및 최적화
│   ├── api/                 # 데이터 API
│   └── database/            # 데이터베이스
├── scripts/                 # 실행 스크립트
├── reports/                 # 분석 리포트
├── tests/                   # 테스트 코드
└── database/                # DB 덤프
```

## 설치 및 실행

### 요구사항

- Python 3.11+
- PostgreSQL 15+
- Docker (optional)

### 설치

```bash
# 가상환경 생성
python -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 등 설정
```

### 데이터베이스 설정

```bash
# Docker로 PostgreSQL 실행
docker-compose up -d

# DB 복원 (선택사항)
docker exec -i stock_postgres psql -U stock -d stock_trading < database/dump.sql
```

### 실행

```bash
# 백테스트 실행
python main.py

# AI 최적화 실행
python scripts/run_iterative_optimization.py
```

## 주요 파일

- `src/analysis/iterative_optimizer.py`: AI 반복 최적화 시스템
- `src/analysis/code_analyzer.py`: GPT-4o 코드 분석기
- `src/analysis/parameter_tester.py`: 파라미터 검증 테스터
- `src/backtest/engine.py`: 백테스트 엔진

## 리포트

최적화 결과는 `reports/` 디렉토리에 JSON 형식으로 저장됩니다:

- `iterative_optimization_final.json`: 최종 최적화 결과
- `final_optimization_report.json`: 기본 최적화 결과
- `backtest_results.json`: 백테스트 결과

## 라이선스

Private - All rights reserved
