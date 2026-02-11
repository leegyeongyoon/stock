#!/usr/bin/env python3
"""RDS → 로컬 DB 동기화 스크립트.

RDS(stock_trading 스키마)의 데이터를 로컬 PostgreSQL로 동기화.
백테스트는 로컬 DB가 3배 빠르므로, 주기적으로 이 스크립트를 실행하여
RDS의 최신 데이터를 로컬에 반영한다.

사용법:
    python scripts/sync_rds_to_local.py              # 전체 동기화
    python scripts/sync_rds_to_local.py --incremental # 증분 동기화 (ohlcv_intraday만)
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.config.settings import Settings

settings = Settings()

# RDS 접속 정보 (DATABASE_URL에서 파싱)
RDS_URL = settings.database_url
LOCAL_URL = settings.backtest_database_url

if not LOCAL_URL:
    print("ERROR: BACKTEST_DATABASE_URL이 .env에 설정되어 있지 않습니다.")
    sys.exit(1)


def parse_pg_url(url: str) -> dict:
    """postgresql://user:pass@host:port/dbname?options=... 파싱."""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    options = parse_qs(parsed.query).get("options", [""])[0]
    schema = "public"
    if "search_path" in options:
        schema = options.split("search_path=")[1].split(",")[0].strip()
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/"),
        "schema": schema,
    }


def run_cmd(cmd: str, env=None) -> tuple[int, str]:
    """Shell 명령 실행."""
    import os
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, env=full_env
    )
    return result.returncode, result.stdout + result.stderr


def full_sync():
    """전체 동기화: RDS stock_trading 스키마 → 로컬 public 스키마."""
    rds = parse_pg_url(RDS_URL)
    local = parse_pg_url(LOCAL_URL)

    print(f"=== RDS → 로컬 전체 동기화 ===")
    print(f"  RDS: {rds['host']}:{rds['port']}/{rds['dbname']} (schema: {rds['schema']})")
    print(f"  로컬: {local['host']}:{local['port']}/{local['dbname']}")
    print()

    dump_file = "/tmp/rds_to_local_dump.sql"

    # Step 1: RDS에서 덤프
    print("[1/3] RDS 데이터 덤프 중...")
    start = time.time()
    pg_env = {"PGPASSWORD": rds["password"]} if rds["password"] else {}
    dump_cmd = (
        f"pg_dump -h {rds['host']} -p {rds['port']} -U {rds['user']} "
        f"-d {rds['dbname']} --schema={rds['schema']} "
        f"--no-owner --no-acl -Fp -f {dump_file}"
    )
    ret, output = run_cmd(dump_cmd, env=pg_env)
    if ret != 0:
        print(f"ERROR: pg_dump 실패\n{output}")
        sys.exit(1)
    print(f"  덤프 완료 ({time.time()-start:.1f}초)")

    # Step 2: 스키마명 변환 (stock_trading → public)
    print("[2/3] 스키마명 변환 중...")
    converted_file = "/tmp/rds_to_local_converted.sql"
    sed_cmd = (
        f"sed "
        f"'s/SET search_path = {rds['schema']}/SET search_path = public/g; "
        f"s/{rds['schema']}\\./{local['schema']}./g; "
        f"s/CREATE SCHEMA {rds['schema']};/-- skip/g; "
        f"s/COMMENT ON SCHEMA {rds['schema']}/-- skip/g' "
        f"{dump_file} > {converted_file}"
    )
    ret, output = run_cmd(sed_cmd)
    if ret != 0:
        print(f"ERROR: sed 변환 실패\n{output}")
        sys.exit(1)
    print("  변환 완료")

    # Step 3: 로컬 DB에 복원 (기존 테이블 삭제 후 재생성)
    print("[3/3] 로컬 DB 복원 중...")
    start = time.time()

    # 기존 테이블 삭제
    tables = [
        "trades", "signals", "backtest_results",
        "investor_trading", "ohlcv_daily", "ohlcv_intraday", "stocks"
    ]
    drop_sql = "; ".join(f"DROP TABLE IF EXISTS {t} CASCADE" for t in tables)
    local_env = {"PGPASSWORD": local["password"]} if local["password"] else {}
    drop_cmd = (
        f"psql -h {local['host']} -p {local['port']} -U {local['user']} "
        f"-d {local['dbname']} -c \"{drop_sql}\""
    )
    run_cmd(drop_cmd, env=local_env)

    # 복원
    restore_cmd = (
        f"psql -h {local['host']} -p {local['port']} -U {local['user']} "
        f"-d {local['dbname']} -f {converted_file}"
    )
    ret, output = run_cmd(restore_cmd, env=local_env)
    if ret != 0 and "ERROR" in output:
        print(f"WARNING: 일부 에러 발생\n{output[-500:]}")
    print(f"  복원 완료 ({time.time()-start:.1f}초)")

    # 검증
    verify(local, local_env, rds, pg_env)


def incremental_sync():
    """증분 동기화: ohlcv_intraday 테이블만 새 데이터 추가."""
    from sqlalchemy import create_engine, text

    rds_engine = create_engine(RDS_URL)
    local_engine = create_engine(LOCAL_URL)

    print("=== 증분 동기화 (ohlcv_intraday) ===")

    # 로컬 최신 datetime 확인
    with local_engine.connect() as conn:
        result = conn.execute(text("SELECT MAX(datetime) FROM ohlcv_intraday"))
        local_max = result.scalar()
    print(f"  로컬 최신: {local_max}")

    if local_max is None:
        print("  로컬에 데이터 없음 → 전체 동기화 필요")
        print("  python scripts/sync_rds_to_local.py (--incremental 없이)")
        return

    # RDS에서 새 데이터 가져오기
    with rds_engine.connect() as conn:
        result = conn.execute(text("SELECT MAX(datetime) FROM ohlcv_intraday"))
        rds_max = result.scalar()
        print(f"  RDS 최신:  {rds_max}")

        if rds_max <= local_max:
            print("  이미 최신 상태입니다.")
            return

        result = conn.execute(
            text("SELECT * FROM ohlcv_intraday WHERE datetime > :dt ORDER BY datetime"),
            {"dt": local_max}
        )
        rows = result.fetchall()
        columns = result.keys()

    print(f"  새 데이터: {len(rows)}건")

    if not rows:
        print("  동기화할 데이터 없음")
        return

    # 로컬에 INSERT
    import pandas as pd
    df = pd.DataFrame(rows, columns=columns)
    df = df.drop(columns=["id"], errors="ignore")

    start = time.time()
    df.to_sql("ohlcv_intraday", local_engine, if_exists="append", index=False)
    print(f"  {len(df)}건 INSERT 완료 ({time.time()-start:.1f}초)")


def verify(local, local_env, rds, pg_env):
    """동기화 결과 검증."""
    from sqlalchemy import create_engine, text

    print("\n=== 검증 ===")
    rds_engine = create_engine(RDS_URL)
    local_engine = create_engine(LOCAL_URL)

    tables = ["stocks", "ohlcv_daily", "ohlcv_intraday", "trades", "backtest_results"]
    for table in tables:
        with rds_engine.connect() as conn:
            rds_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        with local_engine.connect() as conn:
            local_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        status = "OK" if rds_count == local_count else "MISMATCH"
        print(f"  {table:20s}: RDS={rds_count:>10,} / 로컬={local_count:>10,}  [{status}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RDS → 로컬 DB 동기화")
    parser.add_argument("--incremental", action="store_true", help="증분 동기화 (ohlcv_intraday만)")
    args = parser.parse_args()

    if args.incremental:
        incremental_sync()
    else:
        full_sync()
