"""walk_forward_windows 단위 테스트 (순수, 오프라인)."""

import pytest

from src.backtest.walkforward import WFWindow, walk_forward_windows


class TestWalkForward:
    def test_basic_rolling_windows(self):
        dates = list(range(100))
        wins = walk_forward_windows(dates, train_size=44, test_size=15, purge=0)
        # (100 - 44 - 15)//15 + 1 = 41//15 + 1 = 2 + 1 = 3
        assert len(wins) == 3
        for w in wins:
            assert len(w.train) == 44
            assert len(w.test) == 15

    def test_purge_gap_between_train_and_test(self):
        dates = list(range(60))
        wins = walk_forward_windows(dates, train_size=40, test_size=10, purge=2)
        w = wins[0]
        # train [0..39], purge [40,41], test [42..51]
        assert w.train[-1] == 39
        assert w.test[0] == 42
        assert w.test[0] - w.train[-1] == purge_expected()

    def test_test_sets_do_not_overlap_with_default_step(self):
        dates = list(range(100))
        wins = walk_forward_windows(dates, train_size=30, test_size=10)
        seen = set()
        for w in wins:
            assert not (seen & set(w.test)), "검증 구간이 겹치면 안 됨"
            seen |= set(w.test)

    def test_anchored_grows_train(self):
        dates = list(range(80))
        wins = walk_forward_windows(dates, train_size=30, test_size=10, anchored=True)
        assert wins[0].train[0] == 0 and wins[1].train[0] == 0
        assert len(wins[1].train) > len(wins[0].train)

    def test_rolling_keeps_train_fixed(self):
        dates = list(range(80))
        wins = walk_forward_windows(dates, train_size=30, test_size=10, anchored=False)
        assert all(len(w.train) == 30 for w in wins)
        assert wins[1].train[0] > wins[0].train[0]

    def test_insufficient_data_returns_empty(self):
        assert walk_forward_windows(list(range(10)), train_size=20, test_size=5) == []

    def test_sorts_input(self):
        wins = walk_forward_windows([5, 1, 3, 2, 4, 0], train_size=3, test_size=2)
        assert wins[0].train == [0, 1, 2]
        assert wins[0].test == [3, 4]

    def test_invalid_sizes_raise(self):
        with pytest.raises(ValueError):
            walk_forward_windows(list(range(10)), train_size=0, test_size=5)
        with pytest.raises(ValueError):
            walk_forward_windows(list(range(10)), train_size=5, test_size=0)
        with pytest.raises(ValueError):
            walk_forward_windows(list(range(10)), train_size=5, test_size=2, purge=-1)


def purge_expected() -> int:
    # train_end(39) → test_start(42) 사이 간격 = purge(2) + 1
    return 3
