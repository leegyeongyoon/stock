"""Stock universe management - which stocks to monitor and trade."""

from loguru import logger

from src.database.connection import get_session
from src.database.repositories import StockRepository


class StockUniverse:
    """Manages the set of stocks eligible for trading."""

    def __init__(self, codes: list[str] | None = None):
        self._codes: list[str] = codes or []
        self._active_codes: set[str] = set()
        self._names: dict[str, str] = {}

    @property
    def codes(self) -> list[str]:
        return list(self._codes)

    @property
    def active_codes(self) -> set[str]:
        return set(self._active_codes)

    @property
    def count(self) -> int:
        return len(self._codes)

    def get_name(self, code: str) -> str:
        return self._names.get(code, code)

    def load_from_db(self) -> None:
        """Load all active stock codes from database."""
        with get_session() as session:
            repo = StockRepository(session)
            stocks = repo.get_all()
            # 세션 닫히기 전에 속성을 모두 읽어서 plain data로 변환
            codes = [s.code for s in stocks if s.is_active]
            names = {s.code: s.name for s in stocks}

        self._codes = codes
        self._names = names
        self._active_codes = set(self._codes)

        logger.info(f"종목 유니버스 로드: {len(self._codes)}종목")

    def load_from_list(self, codes: list[str]) -> None:
        """Load specific stock codes."""
        self._codes = list(codes)
        self._active_codes = set(codes)
        logger.info(f"종목 유니버스 설정: {len(codes)}종목")

    def get_polling_groups(self, group_size: int = 50) -> list[list[str]]:
        """Split codes into groups for REST polling.

        Returns groups of `group_size` codes for round-robin polling.
        """
        groups = []
        for i in range(0, len(self._codes), group_size):
            groups.append(self._codes[i:i + group_size])
        return groups
