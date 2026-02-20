"""뉴스 분석 모듈 - 네이버 금융 뉴스 크롤링 + GPT 감성분석."""

from src.news.naver_scraper import NaverNewsScraper
from src.news.sentiment import NewsSentimentAnalyzer
from src.news.news_score import compute_news_scores

__all__ = [
    "NaverNewsScraper",
    "NewsSentimentAnalyzer",
    "compute_news_scores",
]
