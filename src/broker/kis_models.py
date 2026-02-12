"""Pydantic models for KIS API request/response data."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "01"
    LIMIT = "00"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TokenInfo(BaseModel):
    """OAuth2 access token."""
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    expires_in: int = 86400


class StockPrice(BaseModel):
    """Current stock price snapshot."""
    code: str
    name: str = ""
    current_price: int
    open_price: int = 0
    high_price: int = 0
    low_price: int = 0
    volume: int = 0
    change_rate: float = 0.0
    timestamp: Optional[datetime] = None


class MinuteBar(BaseModel):
    """5-minute OHLCV bar."""
    code: str
    datetime: datetime
    open: int
    high: int
    low: int
    close: int
    volume: int


class OrderRequest(BaseModel):
    """Order request to KIS API."""
    stock_code: str = Field(..., max_length=6)
    side: OrderSide
    quantity: int = Field(..., gt=0)
    price: int = Field(default=0, ge=0)
    order_type: OrderType = OrderType.MARKET


class OrderResponse(BaseModel):
    """Order execution response from KIS API."""
    success: bool
    order_id: str = ""
    message: str = ""
    rt_cd: str = ""             # 응답코드 (0=성공)
    msg_cd: str = ""            # 메시지코드
    order_number: str = ""      # KIS 주문번호
    order_time: str = ""


class OrderInfo(BaseModel):
    """Current order status."""
    order_id: str
    stock_code: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: int
    filled_quantity: int = 0
    filled_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    strategy_name: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BalanceItem(BaseModel):
    """Single stock holding in balance."""
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: int
    eval_amount: int            # 평가금액
    pnl: int                    # 평가손익
    pnl_rate: float             # 수익률 %


class AccountBalance(BaseModel):
    """Full account balance summary."""
    total_eval: int = 0         # 총 평가금액 (예수금+평가, 모의투자에서 부정확)
    total_deposit: int = 0      # 예수금 (모의투자에서 매수해도 안 줄어듦)
    total_pnl: int = 0          # 총 평가손익
    total_pnl_rate: float = 0.0
    purchase_total: int = 0     # 매입금액합계 (pchs_amt_smtl_amt)
    net_asset: int = 0          # 순자산금액 (nass_amt)
    holdings: list[BalanceItem] = Field(default_factory=list)


class ExecutionInfo(BaseModel):
    """Trade execution (체결) record from KIS."""
    order_id: str
    stock_code: str
    stock_name: str = ""
    side: str                   # "매수" or "매도"
    quantity: int
    price: int
    total_amount: int
    executed_at: Optional[datetime] = None


class WSTickData(BaseModel):
    """Real-time tick data from WebSocket."""
    code: str
    price: int
    volume: int
    timestamp: str
    change_rate: float = 0.0
    ask_price: int = 0
    bid_price: int = 0
