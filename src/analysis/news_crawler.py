"""뉴스 및 이슈 크롤러 - 네이버, 구글, 유튜브"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote, urlencode
from loguru import logger


@dataclass
class NewsItem:
    """뉴스 아이템"""
    title: str
    source: str  # naver, google, youtube
    url: str
    published_at: Optional[datetime] = None
    summary: str = ""
    sentiment: str = "neutral"  # positive, negative, neutral
    relevance_score: float = 0.0


@dataclass
class ThemeNews:
    """테마별 뉴스 모음"""
    theme_name: str
    keywords: list[str]
    news_items: list[NewsItem] = field(default_factory=list)
    hot_score: float = 0.0  # 뉴스 양과 최신성 기반 점수
    sentiment_summary: str = "neutral"
    key_issues: list[str] = field(default_factory=list)


class NewsCrawler:
    """뉴스 크롤러"""

    NAVER_SEARCH_URL = "https://search.naver.com/search.naver"
    NAVER_NEWS_API = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self, naver_client_id: str = "", naver_client_secret: str = ""):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
            timeout=30.0
        )
        self.naver_client_id = naver_client_id
        self.naver_client_secret = naver_client_secret

    async def close(self):
        await self.client.aclose()

    async def search_naver_news(self, keyword: str, max_results: int = 10, days: int = 14) -> list[NewsItem]:
        """네이버 뉴스 검색 (웹 크롤링)

        Args:
            keyword: 검색 키워드
            max_results: 최대 결과 수
            days: 검색 기간 (일) - 기본 14일 (2주)
        """
        news_items = []

        try:
            # 네이버 뉴스 검색
            # pd 옵션: 1=1일, 2=1주, 3=1개월, 4=6개월, 5=1년
            pd_value = "3" if days >= 14 else ("2" if days >= 7 else "1")

            params = {
                "where": "news",
                "query": keyword,
                "sort": "1",  # 최신순
                "pd": pd_value,  # 기간 설정
            }
            url = f"{self.NAVER_SEARCH_URL}?{urlencode(params)}"
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 뉴스 아이템 파싱
            news_list = soup.select('div.news_area')

            for item in news_list[:max_results]:
                try:
                    title_elem = item.select_one('a.news_tit')
                    if not title_elem:
                        continue

                    title = title_elem.get('title', title_elem.text.strip())
                    news_url = title_elem.get('href', '')

                    # 요약
                    summary_elem = item.select_one('div.news_dsc')
                    summary = summary_elem.text.strip() if summary_elem else ""

                    # 날짜
                    date_elem = item.select_one('span.info')
                    published_at = None
                    if date_elem:
                        date_text = date_elem.text.strip()
                        published_at = self._parse_naver_date(date_text)

                    # 감성 분석 (간단한 키워드 기반)
                    sentiment = self._analyze_sentiment(title + " " + summary)

                    news_items.append(NewsItem(
                        title=title,
                        source="naver",
                        url=news_url,
                        published_at=published_at,
                        summary=summary[:200],
                        sentiment=sentiment,
                        relevance_score=self._calculate_relevance(title, keyword)
                    ))

                except Exception as e:
                    logger.debug(f"뉴스 아이템 파싱 실패: {e}")
                    continue

            logger.info(f"네이버 뉴스 '{keyword}': {len(news_items)}건 조회")

        except Exception as e:
            logger.error(f"네이버 뉴스 검색 실패 ({keyword}): {e}")

        return news_items

    async def search_google_news(self, keyword: str, max_results: int = 10) -> list[NewsItem]:
        """구글 뉴스 검색"""
        news_items = []

        try:
            # Google News RSS 활용
            encoded_keyword = quote(keyword)
            url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ko&gl=KR&ceid=KR:ko"

            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, 'xml')

            items = soup.find_all('item')

            for item in items[:max_results]:
                try:
                    title = item.find('title').text if item.find('title') else ""
                    link = item.find('link').text if item.find('link') else ""
                    pub_date = item.find('pubDate').text if item.find('pubDate') else ""

                    # 날짜 파싱
                    published_at = None
                    if pub_date:
                        try:
                            published_at = datetime.strptime(
                                pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                            )
                        except:
                            pass

                    sentiment = self._analyze_sentiment(title)

                    news_items.append(NewsItem(
                        title=title,
                        source="google",
                        url=link,
                        published_at=published_at,
                        sentiment=sentiment,
                        relevance_score=self._calculate_relevance(title, keyword)
                    ))

                except Exception as e:
                    logger.debug(f"구글 뉴스 아이템 파싱 실패: {e}")
                    continue

            logger.info(f"구글 뉴스 '{keyword}': {len(news_items)}건 조회")

        except Exception as e:
            logger.error(f"구글 뉴스 검색 실패 ({keyword}): {e}")

        return news_items

    async def search_youtube(self, keyword: str, max_results: int = 5) -> list[NewsItem]:
        """유튜브 검색 (최근 영상)"""
        news_items = []

        try:
            # YouTube 검색 결과 페이지 크롤링
            encoded_keyword = quote(f"{keyword} 주식")
            url = f"https://www.youtube.com/results?search_query={encoded_keyword}&sp=CAI%253D"  # 최신순

            resp = await self.client.get(url)

            # ytInitialData에서 검색 결과 추출
            import re
            match = re.search(r'var ytInitialData = ({.*?});', resp.text)

            if match:
                import json
                data = json.loads(match.group(1))

                # 검색 결과 파싱
                contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get(
                    'primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])

                for section in contents:
                    items = section.get('itemSectionRenderer', {}).get('contents', [])

                    for item in items[:max_results]:
                        video = item.get('videoRenderer', {})
                        if not video:
                            continue

                        video_id = video.get('videoId', '')
                        title = video.get('title', {}).get('runs', [{}])[0].get('text', '')

                        if not video_id or not title:
                            continue

                        # 게시 시간
                        published_text = video.get('publishedTimeText', {}).get('simpleText', '')

                        news_items.append(NewsItem(
                            title=title,
                            source="youtube",
                            url=f"https://www.youtube.com/watch?v={video_id}",
                            summary=f"YouTube: {published_text}",
                            sentiment=self._analyze_sentiment(title),
                            relevance_score=self._calculate_relevance(title, keyword)
                        ))

            logger.info(f"유튜브 '{keyword}': {len(news_items)}건 조회")

        except Exception as e:
            logger.error(f"유튜브 검색 실패 ({keyword}): {e}")

        return news_items

    async def get_theme_news(self, theme_name: str, keywords: list[str] = None, days: int = 14) -> ThemeNews:
        """테마별 뉴스 종합 조회

        Args:
            theme_name: 테마 이름
            keywords: 검색 키워드 목록
            days: 검색 기간 (일) - 기본 14일 (2주)
        """
        if keywords is None:
            keywords = [theme_name]

        all_news = []

        # 각 키워드로 뉴스 검색
        for keyword in keywords[:3]:  # 최대 3개 키워드
            # 병렬 검색 (2주 기간)
            naver_task = self.search_naver_news(keyword, max_results=10, days=days)
            google_task = self.search_google_news(keyword, max_results=10)
            youtube_task = self.search_youtube(keyword, max_results=3)

            results = await asyncio.gather(naver_task, google_task, youtube_task)

            for news_list in results:
                all_news.extend(news_list)

            await asyncio.sleep(0.3)  # Rate limiting

        # 중복 제거 (제목 유사도 기반)
        unique_news = self._deduplicate_news(all_news)

        # 관련성 점수로 정렬
        unique_news.sort(key=lambda x: x.relevance_score, reverse=True)

        # 핫 스코어 계산
        hot_score = self._calculate_hot_score(unique_news)

        # 감성 요약
        sentiment_summary = self._summarize_sentiment(unique_news)

        # 핵심 이슈 추출
        key_issues = self._extract_key_issues(unique_news)

        return ThemeNews(
            theme_name=theme_name,
            keywords=keywords,
            news_items=unique_news,  # 전체 반환 (제한 없음)
            hot_score=hot_score,
            sentiment_summary=sentiment_summary,
            key_issues=key_issues
        )

    async def get_stock_news(self, stock_name: str, stock_code: str = "", days: int = 14) -> ThemeNews:
        """종목별 뉴스 조회

        Args:
            stock_name: 종목명 (예: 삼성전자)
            stock_code: 종목코드 (선택)
            days: 검색 기간 (일) - 기본 14일 (2주)
        """
        all_news = []

        # 종목명으로 검색
        keywords = [stock_name]

        # 종목명 + 주식 키워드 조합
        search_queries = [
            stock_name,
            f"{stock_name} 주가",
            f"{stock_name} 실적",
        ]

        for query in search_queries:
            # 네이버 뉴스 (메인 소스)
            naver_news = await self.search_naver_news(query, max_results=15, days=days)
            all_news.extend(naver_news)

            # 구글 뉴스
            google_news = await self.search_google_news(query, max_results=10)
            all_news.extend(google_news)

            await asyncio.sleep(0.2)  # Rate limiting

        # 중복 제거
        unique_news = self._deduplicate_news(all_news)

        # 관련성 점수로 정렬 (종목명 포함 우선)
        for item in unique_news:
            if stock_name in item.title:
                item.relevance_score += 0.3

        unique_news.sort(key=lambda x: x.relevance_score, reverse=True)

        # 핫 스코어 계산
        hot_score = self._calculate_hot_score(unique_news)

        # 감성 요약
        sentiment_summary = self._summarize_sentiment(unique_news)

        # 핵심 이슈 추출
        key_issues = self._extract_key_issues(unique_news)

        logger.info(f"종목 뉴스 '{stock_name}': {len(unique_news)}건 조회 (최근 {days}일)")

        return ThemeNews(
            theme_name=stock_name,
            keywords=keywords,
            news_items=unique_news,  # 전체 반환
            hot_score=hot_score,
            sentiment_summary=sentiment_summary,
            key_issues=key_issues
        )

    def _parse_naver_date(self, date_text: str) -> Optional[datetime]:
        """네이버 날짜 텍스트 파싱"""
        now = datetime.now()

        if "분 전" in date_text:
            minutes = int(date_text.replace("분 전", "").strip())
            return now - timedelta(minutes=minutes)
        elif "시간 전" in date_text:
            hours = int(date_text.replace("시간 전", "").strip())
            return now - timedelta(hours=hours)
        elif "일 전" in date_text:
            days = int(date_text.replace("일 전", "").strip())
            return now - timedelta(days=days)

        return None

    def _analyze_sentiment(self, text: str) -> str:
        """간단한 감성 분석 (키워드 기반)"""
        positive_keywords = [
            "상승", "급등", "호재", "기대", "성장", "최고", "돌파", "신고가",
            "수주", "계약", "흑자", "실적", "증가", "확대", "강세", "매수"
        ]
        negative_keywords = [
            "하락", "급락", "악재", "우려", "감소", "적자", "손실", "위기",
            "폭락", "매도", "약세", "실패", "취소", "중단", "철회", "부진"
        ]

        positive_count = sum(1 for kw in positive_keywords if kw in text)
        negative_count = sum(1 for kw in negative_keywords if kw in text)

        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        return "neutral"

    def _calculate_relevance(self, title: str, keyword: str) -> float:
        """관련성 점수 계산"""
        score = 0.0

        # 키워드 포함 여부
        if keyword in title:
            score += 0.5

        # 주식 관련 키워드
        stock_keywords = ["주가", "주식", "종목", "테마", "상승", "하락", "거래"]
        for kw in stock_keywords:
            if kw in title:
                score += 0.1

        return min(score, 1.0)

    def _deduplicate_news(self, news_items: list[NewsItem]) -> list[NewsItem]:
        """중복 뉴스 제거"""
        unique = []
        seen_titles = set()

        for item in news_items:
            # 제목 정규화
            normalized = item.title.lower().replace(" ", "")[:30]

            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique.append(item)

        return unique

    def _calculate_hot_score(self, news_items: list[NewsItem]) -> float:
        """핫 스코어 계산 (뉴스 양 + 최신성)"""
        if not news_items:
            return 0.0

        score = 0.0
        now = datetime.now()

        # 뉴스 양 점수
        score += min(len(news_items) / 10, 1.0) * 50

        # 최신성 점수
        recent_count = 0
        for item in news_items:
            if item.published_at:
                hours_ago = (now - item.published_at).total_seconds() / 3600
                if hours_ago < 6:
                    recent_count += 1

        score += min(recent_count / 5, 1.0) * 30

        # 감성 점수
        positive_count = sum(1 for item in news_items if item.sentiment == "positive")
        score += (positive_count / max(len(news_items), 1)) * 20

        return round(score, 1)

    def _summarize_sentiment(self, news_items: list[NewsItem]) -> str:
        """감성 요약"""
        if not news_items:
            return "neutral"

        sentiments = [item.sentiment for item in news_items]
        positive = sentiments.count("positive")
        negative = sentiments.count("negative")
        total = len(sentiments)

        if positive / total > 0.6:
            return "very_positive"
        elif positive / total > 0.4:
            return "positive"
        elif negative / total > 0.6:
            return "very_negative"
        elif negative / total > 0.4:
            return "negative"
        return "neutral"

    def _extract_key_issues(self, news_items: list[NewsItem]) -> list[str]:
        """핵심 이슈 추출"""
        # 상위 관련성 뉴스의 제목에서 키워드 추출
        key_issues = []

        for item in news_items[:10]:
            if item.relevance_score > 0.3:
                # 제목 정제
                title = item.title
                # 언론사명 제거 등
                if " - " in title:
                    title = title.split(" - ")[0]
                if len(title) > 10:
                    key_issues.append(title[:50])

        return key_issues[:5]  # 상위 5개


# 테마별 검색 키워드 매핑
THEME_KEYWORDS = {
    "2차전지": ["2차전지", "배터리", "리튬", "양극재", "음극재", "전고체"],
    "반도체": ["반도체", "삼성전자", "SK하이닉스", "HBM", "AI반도체", "파운드리"],
    "AI": ["AI", "인공지능", "챗GPT", "엔비디아", "AI반도체", "AI서버"],
    "로봇": ["로봇", "휴머노이드", "협동로봇", "자율주행", "로봇 수주"],
    "바이오": ["바이오", "신약", "임상", "FDA", "제약", "헬스케어"],
    "조선": ["조선", "HD한국조선해양", "삼성중공업", "LNG선", "수주"],
    "방산": ["방산", "방위산업", "한화에어로", "LIG넥스원", "수출"],
    "원전": ["원전", "원자력", "SMR", "두산에너빌리티", "원전 수출"],
    "전력기기": ["전력기기", "변압기", "차단기", "LS일렉트릭", "효성중공업"],
    "게임": ["게임주", "엔씨소프트", "크래프톤", "넷마블", "신작"],
    "엔터": ["엔터", "하이브", "SM", "JYP", "K-POP", "콘서트"],
    "화장품": ["화장품", "K-뷰티", "아모레퍼시픽", "LG생건", "중국 수출"],
}


async def main():
    """테스트 실행"""
    crawler = NewsCrawler()

    try:
        print("뉴스 크롤링 테스트...")

        # 테마별 뉴스 조회
        theme_news = await crawler.get_theme_news(
            "AI",
            keywords=THEME_KEYWORDS.get("AI", ["AI"])
        )

        print(f"\n{'='*60}")
        print(f"테마: {theme_news.theme_name}")
        print(f"핫 스코어: {theme_news.hot_score}")
        print(f"감성: {theme_news.sentiment_summary}")
        print(f"핵심 이슈:")
        for issue in theme_news.key_issues:
            print(f"  - {issue}")

        print(f"\n뉴스 목록 ({len(theme_news.news_items)}건):")
        for item in theme_news.news_items[:10]:
            print(f"  [{item.source}] {item.title[:50]}... ({item.sentiment})")

    finally:
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())
