"""DB 마이그레이션: live_positions 테이블에 새 컬럼 추가 + unique constraint 변경.

새 컬럼:
- stock_name (VARCHAR(50))
- stop_loss_pct (NUMERIC(6,4))
- take_profit_pct (NUMERIC(6,4))
- partial_sold (BOOLEAN DEFAULT FALSE)
- original_quantity (INTEGER)

Constraint 변경:
- DROP uq_live_pos_code_strategy (stock_code + strategy_name)
- ADD uq_live_pos_code (stock_code only)

실행 방법:
    python -m scripts.migrate_live_positions
"""

from sqlalchemy import text

from src.database.connection import get_engine


def migrate():
    engine = get_engine()

    # 1. 새 컬럼 추가 (IF NOT EXISTS로 안전하게)
    columns = [
        ("stock_name", "VARCHAR(50)"),
        ("stop_loss_pct", "NUMERIC(6,4)"),
        ("take_profit_pct", "NUMERIC(6,4)"),
        ("partial_sold", "BOOLEAN DEFAULT FALSE"),
        ("original_quantity", "INTEGER"),
    ]
    for col_name, col_type in columns:
        with engine.begin() as conn:
            try:
                conn.execute(text(
                    f"ALTER TABLE live_positions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  [OK] 컬럼 추가/확인: {col_name} {col_type}")
            except Exception as e:
                print(f"  [ERR] 컬럼 {col_name}: {e}")

    # 2. 기존 unique constraint 제거 (있으면)
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE live_positions DROP CONSTRAINT IF EXISTS uq_live_pos_code_strategy"
            ))
            print("  [OK] 기존 constraint 제거: uq_live_pos_code_strategy")
        except Exception as e:
            print(f"  [SKIP] 기존 constraint 제거 실패: {e}")

    # 3. 새 unique constraint 추가 (stock_code only)
    with engine.begin() as conn:
        try:
            # 중복 데이터 정리: stock_code 기준으로 가장 최근 entry만 유지
            conn.execute(text("""
                DELETE FROM live_positions
                WHERE id NOT IN (
                    SELECT MAX(id) FROM live_positions GROUP BY stock_code
                )
            """))
            conn.execute(text(
                "ALTER TABLE live_positions ADD CONSTRAINT uq_live_pos_code UNIQUE (stock_code)"
            ))
            print("  [OK] 새 constraint 추가: uq_live_pos_code (stock_code)")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  [SKIP] 새 constraint 이미 존재: uq_live_pos_code")
            else:
                print(f"  [ERR] constraint 추가 실패: {e}")

    # 4. 검증
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='live_positions' ORDER BY ordinal_position"
        ))
        cols = [row[0] for row in result]
        print(f"\n현재 컬럼: {cols}")

    print("\n마이그레이션 완료!")


if __name__ == "__main__":
    migrate()
