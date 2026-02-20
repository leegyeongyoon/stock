"""뉴스 확신 점수 계산 - 스크래핑 + 감성분석 통합.

갭 전략과 통합하여 "뉴스가 긍정적인 강한 종목이 갭다운" = 최고의 매수 기회.

사용법 (라이브):
    scores = compute_news_scores(["005930", "000660"])
    # {"005930": 0.7, "000660": -0.3}

사용법 (백테스트):
    # 백테스트에서는 비용/시간 문제로 사전 계산된 캐시 사용 권장
    scores = load_cached_news_scores("cache/news_scores.json")
"""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from src.news.naver_scraper import NaverNewsScraper
from src.news.sentiment import NewsSentimentAnalyzer
from src.utils.logger import get_logger

logger = get_logger(__name__)


def compute_news_scores(
    codes: list[str],
    target_date: Optional[date] = None,
    max_articles: int = 10,
    model: str = "gpt-4o-mini",
) -> dict[str, float]:
    """종목별 뉴스 확신 점수 계산.

    1. 네이버 금융에서 뉴스 크롤링
    2. GPT로 감성분석
    3. 점수 반환 (-1.0 ~ +1.0)

    Args:
        codes: 종목코드 리스트
        target_date: 분석 대상 날짜
        max_articles: 종목당 최대 기사 수
        model: GPT 모델

    Returns:
        {code: score} - score: -1.0 ~ +1.0
    """
    scraper = NaverNewsScraper()
    analyzer = NewsSentimentAnalyzer(model=model)

    # 1. 뉴스 크롤링
    news_data = scraper.fetch_news_batch(
        codes,
        target_date=target_date,
        max_articles_per_code=max_articles,
    )

    if not news_data:
        logger.info(f"뉴스 없음: {len(codes)}종목 조회, 0건")
        return {}

    # 2. 헤드라인 추출
    headlines_by_code = {}
    for code, articles in news_data.items():
        headlines = [a.title for a in articles if a.title]
        if headlines:
            headlines_by_code[code] = headlines

    if not headlines_by_code:
        return {}

    # 3. GPT 감성분석
    date_str = str(target_date) if target_date else None
    results = analyzer.analyze_batch(headlines_by_code, target_date=date_str)

    scores = {}
    for code, (score, reason) in results.items():
        scores[code] = score
        logger.debug(f"뉴스 점수 {code}: {score:+.2f} ({reason})")

    logger.info(
        f"뉴스 분석 완료: {len(scores)}종목, "
        f"긍정 {sum(1 for s in scores.values() if s > 0)}건, "
        f"부정 {sum(1 for s in scores.values() if s < 0)}건"
    )

    return scores


def save_news_scores(scores: dict, filepath: str):
    """뉴스 점수 캐시 저장."""
    # {code: {date_str: score}} 형식으로 저장
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    existing.update(scores)

    with open(path, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_cached_news_scores(filepath: str) -> dict:
    """캐시된 뉴스 점수 로드."""
    path = Path(filepath)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
