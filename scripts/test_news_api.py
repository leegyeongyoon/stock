#!/usr/bin/env python3
"""뉴스 API 모듈 테스트.

네이버 뉴스 크롤링 + GPT 감성분석 동작 확인.

실행:
  source .venv/bin/activate
  python scripts/test_news_api.py              # 기본 테스트 (삼성전자)
  python scripts/test_news_api.py 000660       # 특정 종목
  python scripts/test_news_api.py batch        # 다종목 배치 테스트
"""

import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)


def test_scraper(stock_code: str = "005930"):
    """네이버 뉴스 크롤링 테스트."""
    from src.news.naver_scraper import NaverNewsScraper

    print(f"\n{'=' * 60}")
    print(f"  네이버 뉴스 크롤링 테스트 - {stock_code}")
    print(f"{'=' * 60}")

    scraper = NaverNewsScraper()
    articles = scraper.fetch_news(stock_code, max_pages=2, max_articles=10)

    print(f"\n  크롤링 결과: {len(articles)}건")
    for i, article in enumerate(articles):
        print(f"  {i+1:2d}. [{article.date}] {article.title[:50]}")
        if article.source:
            print(f"      출처: {article.source}")

    return articles


def test_sentiment(stock_code: str = "005930"):
    """GPT 감성분석 테스트."""
    from src.news.naver_scraper import NaverNewsScraper
    from src.news.sentiment import NewsSentimentAnalyzer

    print(f"\n{'=' * 60}")
    print(f"  GPT 감성분석 테스트 - {stock_code}")
    print(f"{'=' * 60}")

    scraper = NaverNewsScraper()
    articles = scraper.fetch_news(stock_code, max_pages=1, max_articles=10)

    if not articles:
        print("  뉴스 없음!")
        return

    headlines = [a.title for a in articles]
    print(f"\n  헤드라인 {len(headlines)}건:")
    for h in headlines[:5]:
        print(f"    - {h[:60]}")

    analyzer = NewsSentimentAnalyzer()
    score, reason = analyzer.analyze_headlines(
        headlines,
        stock_code=stock_code,
        target_date=str(date.today()),
    )

    print(f"\n  감성 점수: {score:+.2f}")
    print(f"  분석 근거: {reason}")

    if score >= 0.5:
        print("  → 긍정적! 갭다운 시 매수 기회")
    elif score <= -0.5:
        print("  → 부정적! 갭다운 시 추가 하락 위험")
    else:
        print("  → 중립")

    return score


def test_batch():
    """다종목 배치 테스트."""
    from src.news.news_score import compute_news_scores

    test_codes = [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "035720",  # 카카오
        "035420",  # NAVER
        "051910",  # LG화학
    ]

    print(f"\n{'=' * 60}")
    print(f"  다종목 배치 뉴스 분석 ({len(test_codes)}종목)")
    print(f"{'=' * 60}")

    scores = compute_news_scores(
        test_codes,
        target_date=date.today(),
        max_articles=5,
    )

    print(f"\n  결과:")
    for code, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        emoji = "+" if score > 0 else "-" if score < 0 else "="
        print(f"  {code}: {score:+.2f} [{emoji}]")

    return scores


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "005930"

    if mode == "batch":
        test_batch()
    else:
        stock_code = mode
        articles = test_scraper(stock_code)
        if articles:
            test_sentiment(stock_code)


if __name__ == "__main__":
    main()
