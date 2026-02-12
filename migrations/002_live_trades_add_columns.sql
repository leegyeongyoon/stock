-- Add missing columns to live_trades for full trade history
-- Run: psql -d honbabnono -f migrations/002_live_trades_add_columns.sql

ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS stock_name VARCHAR(50);
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS entry_price NUMERIC(12,2);
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS pnl_pct NUMERIC(8,4);
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS exit_reason VARCHAR(20);
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS entry_time TIMESTAMPTZ;
