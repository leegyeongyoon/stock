"""Tests for Volume Breakout Strategy."""

from datetime import datetime, date

import pandas as pd
import pytest

from src.strategies.momentum.volume_breakout import VolumeBreakoutStrategy
from src.config.constants import SignalType


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for testing."""
    dates = pd.date_range(start="2024-01-01", periods=30, freq="D")

    data = {
        "open": [10000] * 30,
        "high": [10500] * 30,
        "low": [9500] * 30,
        "close": [10200] * 30,
        "volume": [100000] * 30,
        "value": [1000000000] * 30,
    }

    df = pd.DataFrame(data, index=dates)

    # Create a volume surge on day 25
    df.iloc[24, df.columns.get_loc("volume")] = 500000  # 5x volume
    df.iloc[24, df.columns.get_loc("high")] = 11000
    df.iloc[24, df.columns.get_loc("close")] = 10800

    return df


class TestVolumeBreakoutStrategy:
    """Tests for VolumeBreakoutStrategy."""

    def test_initialization(self):
        """Test strategy initialization with default parameters."""
        strategy = VolumeBreakoutStrategy()

        assert strategy.name == "VolumeBreakout"
        assert strategy.volume_surge_ratio == 3.0
        assert strategy.config.stop_loss == 0.015
        assert strategy.config.take_profit == 0.03

    def test_initialization_with_custom_params(self):
        """Test strategy initialization with custom parameters."""
        strategy = VolumeBreakoutStrategy(
            volume_surge_ratio=4.0,
            stop_loss=0.02,
            take_profit=0.05,
        )

        assert strategy.volume_surge_ratio == 4.0
        assert strategy.config.stop_loss == 0.02
        assert strategy.config.take_profit == 0.05

    def test_generate_signals_with_volume_surge(self, sample_ohlcv_data):
        """Test signal generation when volume surge occurs."""
        strategy = VolumeBreakoutStrategy(volume_surge_ratio=3.0)
        signals = strategy.generate_signals(sample_ohlcv_data, "005930")

        # Should generate at least one signal on the surge day
        assert len(signals) >= 1

        # Check signal properties
        for signal in signals:
            assert signal.code == "005930"
            assert signal.signal_type == SignalType.BUY
            assert signal.strategy_name == "VolumeBreakout"
            assert signal.price > 0
            assert 0 <= signal.strength <= 1

    def test_generate_signals_no_surge(self):
        """Test that no signals are generated without volume surge."""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")
        df = pd.DataFrame({
            "open": [10000] * 30,
            "high": [10100] * 30,
            "low": [9900] * 30,
            "close": [10000] * 30,
            "volume": [100000] * 30,
            "value": [1000000000] * 30,
        }, index=dates)

        strategy = VolumeBreakoutStrategy()
        signals = strategy.generate_signals(df, "005930")

        assert len(signals) == 0

    def test_should_exit_stop_loss(self):
        """Test exit on stop loss."""
        strategy = VolumeBreakoutStrategy(stop_loss=0.02)

        should_exit, reason = strategy.should_exit(
            entry_price=10000,
            current_price=9700,  # -3%
            entry_date=datetime(2024, 1, 1),
            current_date=datetime(2024, 1, 5),
            df=pd.DataFrame(),
        )

        assert should_exit is True
        assert "Stop loss" in reason

    def test_should_exit_take_profit(self):
        """Test exit on take profit."""
        strategy = VolumeBreakoutStrategy(take_profit=0.03)

        should_exit, reason = strategy.should_exit(
            entry_price=10000,
            current_price=10400,  # +4%
            entry_date=datetime(2024, 1, 1),
            current_date=datetime(2024, 1, 5),
            df=pd.DataFrame(),
        )

        assert should_exit is True
        assert "Take profit" in reason

    def test_should_not_exit_within_range(self):
        """Test no exit when price is within stop/profit range."""
        strategy = VolumeBreakoutStrategy(stop_loss=0.02, take_profit=0.03)

        should_exit, reason = strategy.should_exit(
            entry_price=10000,
            current_price=10100,  # +1%
            entry_date=datetime(2024, 1, 1),
            current_date=datetime(2024, 1, 5),
            df=pd.DataFrame(),
        )

        assert should_exit is False
        assert reason == ""

    def test_get_strategy_info(self):
        """Test strategy info retrieval."""
        strategy = VolumeBreakoutStrategy()
        info = strategy.get_strategy_info()

        assert info["name"] == "VolumeBreakout"
        assert "stop_loss" in info
        assert "take_profit" in info
        assert "params" in info
        assert "volume_surge_ratio" in info["params"]
