"""Trade storage - persists completed trades to JSON files by date."""

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "trades"


class TradeStore:
    """Saves/loads completed trades as daily JSON files."""

    def __init__(self, base_dir: Path = STORE_DIR):
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for_date(self, date_str: str) -> Path:
        return self._dir / f"{date_str}.json"

    def save_trade(self, trade: dict) -> None:
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

    def load_trades(self, date_str: str) -> list[dict]:
        path = self._path_for_date(date_str)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def load_all_trades(self) -> list[dict]:
        all_trades = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                all_trades.extend(data)
            except (json.JSONDecodeError, OSError):
                continue
        return all_trades

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
