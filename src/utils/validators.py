"""Input validation utilities."""

import re
from datetime import date

from pydantic import BaseModel, field_validator


class StockCodeValidator(BaseModel):
    """Validator for Korean stock codes."""

    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        """Validate stock code format."""
        if not re.match(r"^\d{6}$", v):
            raise ValueError("Stock code must be 6 digits")
        return v


class DateRangeValidator(BaseModel):
    """Validator for date ranges."""

    start_date: date
    end_date: date

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        """Ensure end_date is after start_date."""
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be after start_date")
        return v


class TradeValidator(BaseModel):
    """Validator for trade parameters."""

    price: int
    quantity: int
    stop_loss: float
    take_profit: float

    @field_validator("price", "quantity")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure positive values."""
        if v <= 0:
            raise ValueError("Value must be positive")
        return v

    @field_validator("stop_loss")
    @classmethod
    def validate_stop_loss(cls, v: float) -> float:
        """Validate stop loss range."""
        if not 0 < v < 1:
            raise ValueError("Stop loss must be between 0 and 1")
        return v

    @field_validator("take_profit")
    @classmethod
    def validate_take_profit(cls, v: float) -> float:
        """Validate take profit range."""
        if not 0 < v < 1:
            raise ValueError("Take profit must be between 0 and 1")
        return v


def is_valid_stock_code(code: str) -> bool:
    """Check if stock code is valid."""
    try:
        StockCodeValidator(code=code)
        return True
    except ValueError:
        return False
