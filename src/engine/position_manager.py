"""Position tracking and P&L calculation for live trading."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from loguru import logger


@dataclass
class LivePosition:
    """A live trading position."""
    stock_code: str
    stock_name: str
    strategy_name: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    stop_loss_pct: float = 0.03      # 3%
    take_profit_pct: float = 0.05    # 5%
    entry_time: datetime = field(default_factory=datetime.now)
    order_id: str = ""
    partial_sold: bool = False        # 분할매도 완료 여부
    original_quantity: int = 0        # 최초 진입 수량

    @property
    def stop_loss_price(self) -> float:
        return self.avg_price * (1 - self.stop_loss_pct)

    @property
    def take_profit_price(self) -> float:
        return self.avg_price * (1 + self.take_profit_pct)

    @property
    def market_value(self) -> float:
        return self.current_price * self.quantity

    @property
    def cost_basis(self) -> float:
        return self.avg_price * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return (self.current_price / self.avg_price - 1) * 100

    @property
    def should_stop_loss(self) -> bool:
        return self.current_price > 0 and self.current_price <= self.stop_loss_price

    @property
    def should_take_profit(self) -> bool:
        return self.current_price > 0 and self.current_price >= self.take_profit_price


@dataclass
class ClosedTrade:
    """A completed (closed) trade record."""
    stock_code: str
    stock_name: str
    strategy_name: str
    side: str               # "BUY"
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    exit_reason: str        # "SL", "TP", "CLOSE", "MANUAL"
    order_id: str = ""


class PositionManager:
    """Tracks all live positions and completed trades."""

    def __init__(self, initial_capital: float, enable_db: bool = True):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._positions: dict[str, LivePosition] = {}
        self._trades: list[ClosedTrade] = []
        self._daily_pnl: float = 0.0
        self._enable_db = enable_db
        self._db_update_counter: int = 0
        # 당일 청산된 종목 코드 → 청산 시각 (재등록 방지용)
        self._recently_closed: dict[str, datetime] = {}

    # ── Commission constants ──────────────────────────────
    COMMISSION_RATE = 0.00015   # 0.015%
    TAX_RATE = 0.0023           # 0.23% (매도세)

    @property
    def positions(self) -> dict[str, LivePosition]:
        return dict(self._positions)

    @property
    def position_count(self) -> int:
        return len(self._positions)

    @property
    def trades_today(self) -> list[ClosedTrade]:
        return list(self._trades)

    @property
    def total_equity(self) -> float:
        holdings = sum(p.market_value for p in self._positions.values())
        return self.cash + holdings

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.total_equity / self.initial_capital - 1) * 100

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        wins = sum(1 for t in self._trades if t.pnl > 0)
        return wins / len(self._trades) * 100

    def has_position(self, code: str) -> bool:
        return code in self._positions

    def get_position(self, code: str) -> Optional[LivePosition]:
        return self._positions.get(code)

    def get_held_codes(self) -> set[str]:
        return set(self._positions.keys())

    def is_recently_closed(self, code: str) -> bool:
        """당일 청산된 종목인지 확인 (재등록 방지)."""
        return code in self._recently_closed

    def get_recently_closed_codes(self) -> set[str]:
        """당일 청산된 종목 코드 세트."""
        return set(self._recently_closed.keys())

    def open_position(
        self,
        stock_code: str,
        stock_name: str,
        strategy_name: str,
        quantity: int,
        price: float,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.05,
        order_id: str = "",
    ) -> LivePosition:
        """Record a new position entry."""
        cost = price * quantity
        commission = cost * self.COMMISSION_RATE
        self.cash -= (cost + commission)

        pos = LivePosition(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=strategy_name,
            quantity=quantity,
            avg_price=price,
            current_price=price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            entry_time=datetime.now(),
            order_id=order_id,
        )
        pos.original_quantity = quantity
        self._positions[stock_code] = pos

        logger.info(
            f"포지션 진입: {stock_code} {quantity}주 @{price:,.0f} "
            f"SL={pos.stop_loss_price:,.0f} TP={pos.take_profit_price:,.0f} "
            f"[{strategy_name}]"
        )

        self._save_position_to_db(pos)
        return pos

    def close_position(
        self, code: str, exit_price: float, exit_reason: str
    ) -> Optional[ClosedTrade]:
        """Close a position and record the trade."""
        pos = self._positions.pop(code, None)
        if not pos:
            return None

        proceeds = exit_price * pos.quantity
        commission = proceeds * self.COMMISSION_RATE
        tax = proceeds * self.TAX_RATE
        self.cash += (proceeds - commission - tax)

        pnl = (exit_price - pos.avg_price) * pos.quantity - commission - tax
        entry_cost = pos.avg_price * pos.quantity
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0.0

        trade = ClosedTrade(
            stock_code=code,
            stock_name=pos.stock_name,
            strategy_name=pos.strategy_name,
            side="BUY",
            quantity=pos.quantity,
            entry_price=pos.avg_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=datetime.now(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            order_id=pos.order_id,
        )
        self._trades.append(trade)
        self._daily_pnl += pnl
        # 청산 기록 → 당일 재등록 방지
        self._recently_closed[code] = datetime.now()

        emoji = "+" if pnl > 0 else ""
        logger.info(
            f"포지션 청산: {code} @{exit_price:,.0f} "
            f"PnL={emoji}{pnl:,.0f} ({emoji}{pnl_pct:.2f}%) "
            f"사유={exit_reason} [{pos.strategy_name}]"
        )

        self._delete_position_from_db(code)
        # trade_store.save_trade()가 DB 저장을 전담 (중복 방지)
        return trade

    def partial_close_position(
        self, code: str, sell_quantity: int, exit_price: float, exit_reason: str
    ) -> Optional[ClosedTrade]:
        """포지션 일부만 청산 (분할매도).

        sell_quantity만큼 팔고, 나머지는 유지.
        partial_sold = True로 마킹.
        """
        pos = self._positions.get(code)
        if not pos:
            return None

        if sell_quantity <= 0 or sell_quantity >= pos.quantity:
            # 전량이면 close_position 사용
            return self.close_position(code, exit_price, exit_reason)

        # 매도 금액 계산
        proceeds = exit_price * sell_quantity
        commission = proceeds * self.COMMISSION_RATE
        tax = proceeds * self.TAX_RATE
        self.cash += (proceeds - commission - tax)

        # PnL 계산 (매도분만)
        pnl = (exit_price - pos.avg_price) * sell_quantity - commission - tax
        entry_cost = pos.avg_price * sell_quantity
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0.0

        # 거래 기록
        trade = ClosedTrade(
            stock_code=code,
            stock_name=pos.stock_name,
            strategy_name=pos.strategy_name,
            side="BUY",
            quantity=sell_quantity,
            entry_price=pos.avg_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=datetime.now(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            order_id=pos.order_id,
        )
        self._trades.append(trade)
        self._daily_pnl += pnl

        # 포지션 수량 감소 + 분할매도 마킹
        pos.quantity -= sell_quantity
        pos.partial_sold = True

        emoji = "+" if pnl > 0 else ""
        logger.info(
            f"분할매도: {code} {sell_quantity}주 @{exit_price:,.0f} "
            f"PnL={emoji}{pnl:,.0f} ({emoji}{pnl_pct:.2f}%) "
            f"잔여={pos.quantity}주 [{pos.strategy_name}]"
        )

        # DB 업데이트 (수량 변경 반영)
        self._save_position_to_db(pos)
        # trade_store.save_trade()가 DB 저장을 전담 (중복 방지)
        return trade

    def update_price(self, code: str, price: float) -> None:
        """Update current price for a position."""
        pos = self._positions.get(code)
        if pos:
            pos.current_price = price

    def update_prices(self, prices: dict[str, float]) -> None:
        """Batch update prices for all positions."""
        for code, price in prices.items():
            self.update_price(code, price)

        self._db_update_counter += 1
        if self._db_update_counter >= 3:  # Every 15s (3 calls * 5s interval)
            self._db_update_counter = 0
            self._sync_prices_to_db()

    def recover_trades_from_db(self) -> int:
        """Recover today's completed trades from DB on restart.

        Populates _trades and _daily_pnl so dashboard shows correct
        trade history and performance data after server restart.
        Returns number of trades recovered.
        """
        if not self._enable_db:
            return 0
        try:
            from src.database.connection import get_session
            from src.database.repositories import LiveTradeRepository

            with get_session() as session:
                repo = LiveTradeRepository(session)
                db_trades = repo.get_today()

                if not db_trades:
                    logger.info("DB에 복구할 오늘 거래내역 없음")
                    return 0

                recovered = 0
                for t in db_trades:
                    trade = ClosedTrade(
                        stock_code=t.stock_code,
                        stock_name=t.stock_name or t.stock_code,
                        strategy_name=t.strategy_name or "",
                        side=t.side,
                        quantity=t.quantity,
                        entry_price=float(t.entry_price) if t.entry_price else 0.0,
                        exit_price=float(t.price) if t.price else 0.0,
                        entry_time=t.entry_time or t.traded_at,
                        exit_time=t.traded_at,
                        pnl=float(t.pnl) if t.pnl else 0.0,
                        pnl_pct=float(t.pnl_pct) if t.pnl_pct else 0.0,
                        exit_reason=t.exit_reason or "",
                        order_id=str(t.order_id) if t.order_id else "",
                    )
                    self._trades.append(trade)
                    self._daily_pnl += trade.pnl
                    # 청산 기록 복원 (재등록 방지)
                    self._recently_closed[t.stock_code] = t.traded_at
                    recovered += 1

                logger.info(
                    f"DB에서 오늘 거래 {recovered}건 복구 "
                    f"(일일손익: {self._daily_pnl:+,.0f}원)"
                )
                return recovered

        except Exception as e:
            logger.warning(f"거래내역 DB 복구 실패 (무시): {e}")
            return 0

    def reset_daily(self) -> None:
        """Reset daily counters for a new trading day."""
        self._daily_pnl = 0.0
        self._trades.clear()
        self._recently_closed.clear()

    def get_summary(self) -> dict:
        return {
            "total_equity": int(self.total_equity),
            "cash": int(self.cash),
            "positions": self.position_count,
            "daily_pnl": int(self._daily_pnl),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "trades_today": len(self._trades),
            "win_rate": round(self.win_rate, 1),
        }

    # ── DB Persistence Helpers ─────────────────────────────

    def load_from_db(self) -> int:
        """DB에서 포지션 복구 → 메모리 _positions에 로드.

        엔진 시작 시 _sync_balance() 이전에 호출하여
        전략 이름이 '기존보유'로 덮어씌워지는 것을 방지.
        Returns number of positions loaded.
        """
        if not self._enable_db:
            return 0
        try:
            from src.database.connection import get_session
            from src.database.repositories import LivePositionRepository

            with get_session() as session:
                repo = LivePositionRepository(session)
                db_positions = repo.get_all()

                if not db_positions:
                    logger.info("DB에 복구할 포지션 없음")
                    return 0

                loaded = 0
                for p in db_positions:
                    code = p.stock_code
                    if code in self._positions:
                        continue

                    pos = LivePosition(
                        stock_code=code,
                        stock_name=p.stock_name or code,
                        strategy_name=p.strategy_name or "복구",
                        quantity=p.quantity,
                        avg_price=float(p.avg_price) if p.avg_price else 0.0,
                        current_price=float(p.current_price) if p.current_price else 0.0,
                        stop_loss_pct=float(p.stop_loss_pct) if p.stop_loss_pct else 0.03,
                        take_profit_pct=float(p.take_profit_pct) if p.take_profit_pct else 0.05,
                        entry_time=p.entry_time or datetime.now(),
                        partial_sold=p.partial_sold or False,
                        original_quantity=p.original_quantity or p.quantity,
                    )
                    self._positions[code] = pos
                    loaded += 1

                if loaded > 0:
                    logger.info(
                        f"DB에서 {loaded}개 포지션 로드 완료 "
                        f"(전략: {', '.join(p.strategy_name for p in self._positions.values())})"
                    )
                return loaded

        except Exception as e:
            logger.warning(f"포지션 DB 로드 실패 (무시): {e}")
            return 0

    def _save_position_to_db(self, pos: LivePosition) -> None:
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LivePositionRepository

            with get_session() as session:
                repo = LivePositionRepository(session)
                repo.upsert({
                    "stock_code": pos.stock_code,
                    "stock_name": pos.stock_name,
                    "strategy_name": pos.strategy_name,
                    "quantity": pos.quantity,
                    "avg_price": Decimal(str(pos.avg_price)),
                    "current_price": Decimal(str(pos.current_price)),
                    "unrealized_pnl": Decimal(str(pos.unrealized_pnl)),
                    "stop_loss_pct": pos.stop_loss_pct,
                    "take_profit_pct": pos.take_profit_pct,
                    "stop_loss_price": Decimal(str(pos.stop_loss_price)),
                    "take_profit_price": Decimal(str(pos.take_profit_price)),
                    "entry_time": pos.entry_time,
                    "partial_sold": pos.partial_sold,
                    "original_quantity": pos.original_quantity,
                })
        except Exception as e:
            logger.warning(f"포지션 DB 저장 실패 (메모리 상태 유지): {e}")

    def _delete_position_from_db(self, code: str) -> None:
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LivePositionRepository

            with get_session() as session:
                repo = LivePositionRepository(session)
                repo.delete_by_code(code)
        except Exception as e:
            logger.warning(f"포지션 DB 삭제 실패: {e}")

    def _save_trade_to_db(self, trade: ClosedTrade) -> None:
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LiveTradeRepository

            with get_session() as session:
                repo = LiveTradeRepository(session)
                repo.create({
                    "order_id": trade.order_id if trade.order_id else None,
                    "stock_code": trade.stock_code,
                    "strategy_name": trade.strategy_name,
                    "side": trade.side,
                    "quantity": trade.quantity,
                    "price": Decimal(str(trade.exit_price)),
                    "pnl": Decimal(str(trade.pnl)),
                    "traded_at": trade.exit_time,
                })
        except Exception as e:
            logger.warning(f"거래 DB 저장 실패: {e}")

    def _sync_prices_to_db(self) -> None:
        if not self._enable_db or not self._positions:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LivePositionRepository

            updates = [
                {
                    "stock_code": pos.stock_code,
                    "current_price": pos.current_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                }
                for pos in self._positions.values()
            ]
            with get_session() as session:
                repo = LivePositionRepository(session)
                repo.update_prices(updates)
        except Exception as e:
            logger.debug(f"포지션 가격 DB 동기화 실패: {e}")
