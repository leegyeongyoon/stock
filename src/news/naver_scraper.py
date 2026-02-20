"""네이버 금융 뉴스 스크래퍼.

종목코드로 네이버 금융 뉴스 헤드라인 + 요약을 크롤링.
실시간/백테스트 모두 사용 가능.

사용법:
    scraper = NaverNewsScraper()
    articles = scraper.fetch_news("005930", max_pages=2)
    # [{"title": "삼성전자 ...", "date": "2025-01-15", "source": "한경"}, ...]
"""

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 네이버 금융 뉴스 URL
NAVER_NEWS_URL = "https://finance.naver.com/item/news_news.naver"
# 종목 관련 뉴스 (종합)
NAVER_NEWS_READ_URL = "https://finance.naver.com/item/news_read.naver"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}

# 요청 간 딜레이 (서버 부하 방지)
REQUEST_DELAY = 0.3


@dataclass
class NewsArticle:
    """뉴스 기사 데이터."""
    title: str
    date: date
    source: str = ""
    url: str = ""
    summary: str = ""


class NaverNewsScraper:
    """네이버 금융 뉴스 스크래퍼."""

    def __init__(self, delay: float = REQUEST_DELAY):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._delay = delay
        self._cache: dict[str, list[NewsArticle]] = {}

    def fetch_news(
        self,
        stock_code: str,
        target_date: Optional[date] = None,
        max_pages: int = 3,
        max_articles: int = 20,
    ) -> list[NewsArticle]:
        """종목 뉴스 크롤링.

        Args:
            stock_code: 6자리 종목코드
            target_date: 특정 날짜 뉴스만 필터 (None=전체)
            max_pages: 최대 크롤링 페이지 수
            max_articles: 최대 기사 수

        Returns:
            NewsArticle 리스트 (최신순)
        """
        cache_key = f"{stock_code}_{target_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        articles = []

        for page in range(1, max_pages + 1):
            try:
                page_articles = self._fetch_page(stock_code, page)
                if not page_articles:
                    break

                for article in page_articles:
                    if target_date and article.date != target_date:
                        # 날짜가 target_date 이전이면 중단
                        if article.date < target_date:
                            break
                        continue
                    articles.append(article)
                    if len(articles) >= max_articles:
                        break

                if len(articles) >= max_articles:
                    break

                time.sleep(self._delay)

            except Exception as e:
                logger.debug(f"뉴스 크롤링 실패 {stock_code} p{page}: {e}")
                break

        self._cache[cache_key] = articles
        return articles

    def fetch_news_batch(
        self,
        codes: list[str],
        target_date: Optional[date] = None,
        max_articles_per_code: int = 10,
    ) -> dict[str, list[NewsArticle]]:
        """여러 종목 뉴스 벌크 크롤링.

        Args:
            codes: 종목코드 리스트
            target_date: 특정 날짜 필터
            max_articles_per_code: 종목당 최대 기사 수

        Returns:
            {code: [NewsArticle, ...]}
        """
        result = {}
        for code in codes:
            articles = self.fetch_news(
                code,
                target_date=target_date,
                max_pages=2,
                max_articles=max_articles_per_code,
            )
            if articles:
                result[code] = articles
        return result

    def _fetch_page(self, stock_code: str, page: int) -> list[NewsArticle]:
        """한 페이지 뉴스 파싱."""
        params = {
            "code": stock_code,
            "page": page,
            "sm": "title_entity_id.basic",
            "clusterId": "",
        }

        resp = self._session.get(NAVER_NEWS_URL, params=params, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        # 뉴스 테이블에서 기사 추출
        rows = soup.select("table.type5 tbody tr")

        for row in rows:
            # 관계없는 행 스킵
            if row.get("class") and "relation_lst" in " ".join(row.get("class", [])):
                continue

            title_tag = row.select_one("td.title a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            if not title:
                continue

            url = title_tag.get("href", "")
            if url and not url.startswith("http"):
                url = "https://finance.naver.com" + url

            # 날짜/출처 파싱
            info_tag = row.select_one("td.info")
            source = info_tag.get_text(strip=True) if info_tag else ""

            date_tag = row.select_one("td.date")
            article_date = self._parse_date(
                date_tag.get_text(strip=True) if date_tag else ""
            )

            articles.append(NewsArticle(
                title=title,
                date=article_date,
                source=source,
                url=url,
            ))

        return articles

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """날짜 문자열 파싱."""
        date_str = date_str.strip()
        if not date_str:
            return date.today()

        # "2025.01.15 09:30" 형식
        match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", date_str)
        if match:
            return date(int(match[1]), int(match[2]), int(match[3]))

        # "1시간전", "2일전" 등
        if "시간전" in date_str or "분전" in date_str:
            return date.today()
        if "일전" in date_str:
            days = int(re.search(r"(\d+)", date_str).group(1))
            return date.today() - timedelta(days=days)

        return date.today()

    def clear_cache(self):
        """캐시 초기화."""
        self._cache.clear()
