-- Live trading tables for auto-trading server
-- Run: psql -d stock_trading -f migrations/001_live_trading_tables.sql

CREATE TABLE IF NOT EXISTS live_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) UNIQUE,
    stock_code VARCHAR(10) NOT NULL,
    strategy_name VARCHAR(50),
    side VARCHAR(4) NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC(12,2),
    status VARCHAR(20) NOT NULL,
    filled_quantity INTEGER DEFAULT 0,
    filled_price NUMERIC(12,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS live_positions (
    id SERIAL PRIMARY KEY,
    stock_code VARCHAR(10) NOT NULL,
    strategy_name VARCHAR(50),
    quantity INTEGER NOT NULL,
    avg_price NUMERIC(12,2) NOT NULL,
    current_price NUMERIC(12,2),
    unrealized_pnl NUMERIC(12,2),
    stop_loss_price NUMERIC(12,2),
    take_profit_price NUMERIC(12,2),
    entry_time TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS live_trades (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) REFERENCES live_orders(order_id),
    stock_code VARCHAR(10) NOT NULL,
    strategy_name VARCHAR(50),
    side VARCHAR(4) NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC(12,2) NOT NULL,
    pnl NUMERIC(12,2),
    traded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    total_equity NUMERIC(14,2),
    daily_pnl NUMERIC(12,2),
    daily_return NUMERIC(8,4),
    total_trades INTEGER,
    win_rate NUMERIC(5,2)
);

CREATE TABLE IF NOT EXISTS system_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(30) NOT NULL,
    severity VARCHAR(10) DEFAULT 'INFO',
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS strategy_performance (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    strategy_name VARCHAR(50) NOT NULL,
    trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    pnl NUMERIC(12,2) DEFAULT 0,
    UNIQUE(date, strategy_name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_live_orders_status ON live_orders(status);
CREATE INDEX IF NOT EXISTS idx_live_orders_stock ON live_orders(stock_code);
CREATE INDEX IF NOT EXISTS idx_live_trades_stock ON live_trades(stock_code);
CREATE INDEX IF NOT EXISTS idx_live_trades_date ON live_trades(traded_at);
CREATE INDEX IF NOT EXISTS idx_system_events_type ON system_events(event_type);
CREATE INDEX IF NOT EXISTS idx_system_events_date ON system_events(created_at);
CREATE INDEX IF NOT EXISTS idx_strategy_perf_date ON strategy_performance(date);
