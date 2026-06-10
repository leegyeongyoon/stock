"""Purged walk-forward 분할기.

단일 IS/OOS 분할(예: 44일/15일)은 한 번의 운 좋은 OOS에 과적합되기 쉽다. 롤링 원점
방식으로 K개의 (train, purge, test) 윈도우를 만들어 대부분 윈도우에서 살아남는 파라미터만
채택하게 한다. purge gap은 train→test 경계를 걸치는 인트라데이 포지션의 누수를 막는다.

순수 함수(날짜 리스트만 다룸) — 오프라인 테스트 가능.
"""

from dataclasses import dataclass
from typing import Optional, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class WFWindow:
    """하나의 walk-forward 윈도우(학습/검증 날짜 집합)."""

    index: int
    train: list
    test: list

    @property
    def train_span(self) -> tuple:
        return (self.train[0], self.train[-1]) if self.train else (None, None)

    @property
    def test_span(self) -> tuple:
        return (self.test[0], self.test[-1]) if self.test else (None, None)


def walk_forward_windows(
    dates: Sequence[T],
    *,
    train_size: int,
    test_size: int,
    purge: int = 0,
    step: Optional[int] = None,
    anchored: bool = False,
) -> list[WFWindow]:
    """롤링 (train, purge, test) 윈도우 리스트 생성.

    Args:
        dates: 정렬 가능한 날짜(혹은 라벨) 시퀀스. 내부에서 정렬한다.
        train_size: 학습 구간 길이(원소 수).
        test_size: 검증 구간 길이.
        purge: train 과 test 사이에 버리는 원소 수(경계 누수 차단).
        step: 다음 윈도우로 이동할 간격. 기본은 test_size(검증 구간 비중첩).
        anchored: True면 train 시작을 0에 고정(train 이 점점 커짐), False면 고정 길이 롤링.

    Returns:
        만들 수 있는 모든 윈도우. 데이터가 부족하면 빈 리스트.
    """
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size 와 test_size 는 양수여야 합니다")
    if purge < 0:
        raise ValueError("purge 는 음수일 수 없습니다")

    ordered = sorted(dates)
    n = len(ordered)
    move = step if step is not None else test_size
    if move <= 0:
        raise ValueError("step 은 양수여야 합니다")

    windows: list[WFWindow] = []
    start = 0
    idx = 0
    while True:
        train_start = 0 if anchored else start
        train_end = start + train_size  # exclusive
        test_start = train_end + purge
        test_end = test_start + test_size
        if test_end > n:
            break
        windows.append(
            WFWindow(
                index=idx,
                train=ordered[train_start:train_end],
                test=ordered[test_start:test_end],
            )
        )
        idx += 1
        start += move

    return windows
