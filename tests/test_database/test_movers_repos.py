"""데이터 기반 리포지토리의 멱등 upsert 검증.

DB 연결 없이도 돌도록 upsert 문(statement)을 Postgres 방언으로 컴파일해
ON CONFLICT 대상(제약/인덱스)과 DO UPDATE 가 올바른지 정적으로 검증한다.
실제 DB가 있으면(BACKTEST_DATABASE_URL/DATABASE_URL) 진짜 round-trip 멱등성도 확인한다.
"""

from datetime import date, datetime

import pytest
from sqlalchemy.dialects import postgresql

from src.database.repositories import (
    DailyHotThemeRepository,
    DailyMoversRepository,
    LimitEventRepository,
    OHLCVIntradayRepository,
    StockThemeRepository,
)


class _CapturingSession:
    """execute()에 들어온 statement를 잡아두는 가짜 세션."""

    def __init__(self):
        self.last = None

    def execute(self, stmt):
        self.last = stmt
        return None


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _movers_record() -> dict:
    return {
        "date": date(2026, 6, 10), "code": "005930", "market": "KOSPI",
        "open": 1000, "high": 1300, "low": 1000, "close": 1300,
        "change_rate": 30.0, "volume": 1_000_000, "value": 2_000_000_000,
        "market_cap": 50_000_000_000, "volume_ratio": 5.0,
        "is_limit_up": True, "is_limit_down": False,
        "rank_change": 1, "rank_value": 2, "rank_volume_ratio": 1,
        "flags": ["top_gainer", "limit_up"], "theme_tags": None,
    }


class TestUpsertStatementConstruction:
    def test_daily_movers_targets_named_constraint(self):
        s = _CapturingSession()
        n = DailyMoversRepository(s).upsert_many([_movers_record()])
        assert n == 1
        sql = _sql(s.last)
        assert "INSERT INTO daily_movers" in sql
        assert "ON CONFLICT ON CONSTRAINT uq_daily_movers_date_code" in sql
        assert "DO UPDATE" in sql

    def test_intraday_uses_column_inference_not_named_constraint(self):
        # 기존 raw 테이블과 공존하므로 제약 이름이 아닌 컬럼 집합으로 충돌 지정해야 함
        s = _CapturingSession()
        OHLCVIntradayRepository(s).upsert_many(
            [{"code": "005930", "datetime": datetime(2026, 6, 10, 9, 1),
              "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "interval": "1m"}]
        )
        sql = _sql(s.last)
        assert "ON CONFLICT (code, datetime, interval)" in sql
        assert "ON CONSTRAINT" not in sql

    def test_limit_events_targets_named_constraint(self):
        s = _CapturingSession()
        LimitEventRepository(s).upsert_many(
            [{"date": date(2026, 6, 10), "code": "005930", "event_type": "limit_up",
              "limit_price": 1300, "first_hit_time": None, "hit_count": 0,
              "closed_at_limit": True, "source": "daily_inferred"}]
        )
        sql = _sql(s.last)
        assert "ON CONFLICT ON CONSTRAINT uq_limit_events_date_code_type" in sql

    def test_stock_theme_targets_named_constraint(self):
        s = _CapturingSession()
        StockThemeRepository(s).upsert_many(
            [{"date": date(2026, 6, 10), "code": "005930",
              "theme_code": "AI", "theme_name": "AI", "is_leader": True}]
        )
        assert "ON CONFLICT ON CONSTRAINT uq_stock_themes_date_code_theme" in _sql(s.last)

    def test_hot_theme_targets_named_constraint(self):
        s = _CapturingSession()
        DailyHotThemeRepository(s).upsert_many(
            [{"date": date(2026, 6, 10), "theme_code": "AI", "theme_name": "AI", "rank": 1}]
        )
        assert "ON CONFLICT ON CONSTRAINT uq_daily_hot_themes_date_theme" in _sql(s.last)

    def test_empty_records_noop(self):
        s = _CapturingSession()
        assert DailyMoversRepository(s).upsert_many([]) == 0
        assert s.last is None


# ── 실제 DB가 있을 때만 도는 멱등성 round-trip (없으면 skip) ──────────────


def _backtest_session_or_skip():
    try:
        from sqlalchemy.orm import sessionmaker

        from src.database.connection import get_backtest_engine
        from src.database.models import Base

        engine = get_backtest_engine()
        conn = engine.connect()
        conn.close()
        Base.metadata.create_all(
            bind=engine, tables=[Base.metadata.tables["daily_movers"]]
        )
        return sessionmaker(bind=engine)
    except Exception as e:  # noqa: BLE001 - DB 미가용이면 통합 테스트 skip
        pytest.skip(f"DB 미가용 — 통합 멱등성 테스트 skip: {e}")


@pytest.mark.integration
def test_daily_movers_upsert_idempotent_roundtrip():
    factory = _backtest_session_or_skip()
    rec = _movers_record()
    rec["code"] = "TESTIDEMP"

    with factory() as s:
        DailyMoversRepository(s).upsert_many([rec])
        s.commit()
    # 같은 키 재삽입 → 행 추가 없이 값 갱신
    rec2 = {**rec, "change_rate": 12.34, "flags": ["value_top"]}
    with factory() as s:
        DailyMoversRepository(s).upsert_many([rec2])
        s.commit()
    with factory() as s:
        rows = DailyMoversRepository(s).get_for_date(rec["date"])
        mine = [r for r in rows if r.code == "TESTIDEMP"]
        assert len(mine) == 1
        assert float(mine[0].change_rate) == pytest.approx(12.34)
        s.delete(mine[0])
        s.commit()
