"""Trade storage - persists completed trades to JSON files by date."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from loguru import logger

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "trades"


class TradeStore:
    """Saves/loads completed trades as daily JSON files + DB dual storage."""

    def __init__(self, base_dir: Path = STORE_DIR, enable_db: bool = True):
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._enable_db = enable_db

    def _path_for_date(self, date_str: str) -> Path:
        return self._dir / f"{date_str}.json"

    def save_trade(self, trade: dict) -> None:
        # 1. JSON backup (always)
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = self._path_for_date(date_str)

        trades = []
        if path.exists():
            try:
                trades = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                trades = []

        trades.append(trade)
        path.write_text(json.dumps(trades, ensure_ascii=False, indent=2), encoding="utf-8")

        # 2. DB primary storage
        self._save_to_db(trade)

    def load_trades(self, date_str: str) -> list[dict]:
        path = self._path_for_date(date_str)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def load_all_trades(self) -> list[dict]:
        # 1. Try DB first (persistent across container restarts)
        db_trades = self._load_from_db()
        if db_trades:
            return db_trades

        # 2. Fallback to JSON files (local only)
        all_trades = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                all_trades.extend(data)
            except (json.JSONDecodeError, OSError):
                continue
        return all_trades

    def _load_from_db(self) -> list[dict]:
        """Load all trades from DB."""
        if not self._enable_db:
            return []
        try:
            from src.database.connection import get_session
            from src.database.models import LiveTrade
            from sqlalchemy import select

            with get_session() as session:
                query = select(LiveTrade).order_by(LiveTrade.traded_at)
                trades = list(session.execute(query).scalars().all())
                return [
                    {
                        "stock_code": t.stock_code,
                        "stock_name": t.stock_name or t.stock_code,
                        "strategy_name": t.strategy_name or "",
                        "side": t.side,
                        "quantity": t.quantity,
                        "entry_price": int(t.entry_price) if t.entry_price else 0,
                        "exit_price": int(t.price) if t.price else 0,
                        "pnl": int(t.pnl) if t.pnl else 0,
                        "pnl_pct": round(float(t.pnl_pct), 2) if t.pnl_pct else 0,
                        "exit_reason": t.exit_reason or "",
                        "entry_time": t.entry_time.isoformat() if t.entry_time else "",
                        "exit_time": t.traded_at.isoformat() if t.traded_at else "",
                    }
                    for t in trades
                ]
        except Exception as e:
            logger.warning(f"거래 DB 조회 실패, JSON 폴백: {e}")
            return []

    def get_by_day_of_week(self) -> dict[str, dict]:
        """Aggregate trades by day of week (월~금)."""
        day_names = ["월", "화", "수", "목", "금"]
        result = {
            d: {"trades": 0, "wins": 0, "total_pnl": 0.0}
            for d in day_names
        }

        for trade in self.load_all_trades():
            exit_time = trade.get("exit_time", "")
            try:
                dt = datetime.fromisoformat(exit_time)
                dow = dt.weekday()
                if dow > 4:
                    continue
                day = day_names[dow]
                result[day]["trades"] += 1
                result[day]["total_pnl"] += trade.get("pnl", 0)
                if trade.get("pnl", 0) > 0:
                    result[day]["wins"] += 1
            except (ValueError, IndexError):
                continue

        return result

    def get_by_strategy(self) -> dict[str, dict]:
        """Aggregate trades by strategy name."""
        result: dict[str, dict] = {}
        for trade in self.load_all_trades():
            sn = trade.get("strategy_name", "unknown")
            if sn not in result:
                result[sn] = {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0.0, "max_win": 0.0, "max_loss": 0.0,
                    "pnl_list": [],
                }
            r = result[sn]
            pnl = trade.get("pnl", 0)
            r["trades"] += 1
            r["total_pnl"] += pnl
            r["pnl_list"].append(pnl)
            if pnl > 0:
                r["wins"] += 1
                r["max_win"] = max(r["max_win"], pnl)
            else:
                r["losses"] += 1
                r["max_loss"] = min(r["max_loss"], pnl)
        return result

    def _save_to_db(self, trade: dict) -> None:
        """Save trade to live_trades DB table (best-effort)."""
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LiveTradeRepository

            exit_time = trade.get("exit_time", "")
            if isinstance(exit_time, str) and exit_time:
                traded_at = datetime.fromisoformat(exit_time)
            else:
                traded_at = datetime.now()

            entry_time = trade.get("entry_time", "")
            entry_at = None
            if isinstance(entry_time, str) and entry_time:
                try:
                    entry_at = datetime.fromisoformat(entry_time)
                except ValueError:
                    pass

            with get_session() as session:
                repo = LiveTradeRepository(session)
                repo.create({
                    "stock_code": trade.get("stock_code", ""),
                    "stock_name": trade.get("stock_name", ""),
                    "strategy_name": trade.get("strategy_name", ""),
                    "side": trade.get("side", "BUY"),
                    "quantity": trade.get("quantity", 0),
                    "entry_price": Decimal(str(trade.get("entry_price", 0))),
                    "price": Decimal(str(trade.get("exit_price", 0))),
                    "pnl": Decimal(str(trade.get("pnl", 0))),
                    "pnl_pct": trade.get("pnl_pct", 0),
                    "exit_reason": trade.get("exit_reason", ""),
                    "entry_time": entry_at,
                    "traded_at": traded_at,
                })
        except Exception as e:
            logger.warning(f"거래 DB 저장 실패 (JSON 백업은 완료): {e}")
