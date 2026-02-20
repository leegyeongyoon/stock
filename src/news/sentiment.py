"""GPT 기반 뉴스 감성분석.

뉴스 헤드라인 묶음을 GPT에게 보내서 주가 영향도 분석.
결과: -1.0 (매우 부정) ~ +1.0 (매우 긍정)

사용법:
    analyzer = NewsSentimentAnalyzer()
    score = analyzer.analyze_headlines(["삼성전자 실적 호조", "수출 증가"])
    # 0.7 (긍정)

비용 절감:
    - 헤드라인만 분석 (본문 X)
    - 최대 20개 헤드라인을 1회 API 콜로 처리
    - gpt-4o-mini 사용 (저렴 + 빠름)
"""

import json
from typing import Optional

from openai import OpenAI

from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """당신은 한국 주식시장 전문 뉴스 분석가입니다.
주어진 뉴스 헤드라인들을 분석하여 해당 종목의 주가에 미치는 영향을 평가하세요.

평가 기준:
- 실적 호조, 수주, 신사업, 기관매수, 외국인매수 → 긍정
- 실적 부진, 소송, 규제, 하향, 매도 → 부정
- 시장 일반, 섹터 뉴스, 중립적 내용 → 중립
- 전일 급등/상한가 후 다음날 뉴스가 긍정적 → 추가 상승 가능성 높음

응답 형식 (JSON만):
{"score": float, "reason": "한줄 요약"}

score 범위:
- -1.0: 매우 부정 (주가 하락 예상)
- -0.5: 부정
- 0.0: 중립
- +0.5: 긍정
- +1.0: 매우 긍정 (주가 상승 예상)"""

USER_PROMPT_TEMPLATE = """종목: {stock_name} ({stock_code})
날짜: {date}

뉴스 헤드라인 ({n}건):
{headlines}

이 종목의 오늘 주가 전망을 -1.0 ~ +1.0 점수로 평가하세요."""


class NewsSentimentAnalyzer:
    """GPT 기반 뉴스 감성분석기."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
    ):
        self._model = model
        key = api_key or settings.openai_api_key
        if not key:
            raise ValueError("OPENAI_API_KEY not configured")
        self._client = OpenAI(api_key=key)
        self._cache: dict[str, float] = {}

    def analyze_headlines(
        self,
        headlines: list[str],
        stock_code: str = "",
        stock_name: str = "",
        target_date: Optional[str] = None,
    ) -> tuple[float, str]:
        """뉴스 헤드라인 감성분석.

        Args:
            headlines: 뉴스 헤드라인 리스트
            stock_code: 종목코드
            stock_name: 종목명
            target_date: 날짜 문자열

        Returns:
            (score, reason) - score: -1.0~+1.0, reason: 한줄 요약
        """
        if not headlines:
            return 0.0, "뉴스 없음"

        cache_key = f"{stock_code}_{target_date}_{hash(tuple(headlines[:5]))}"
        if cache_key in self._cache:
            return self._cache[cache_key], "cached"

        headlines_text = "\n".join(
            f"  {i+1}. {h}" for i, h in enumerate(headlines[:20])
        )

        user_msg = USER_PROMPT_TEMPLATE.format(
            stock_name=stock_name or stock_code,
            stock_code=stock_code,
            date=target_date or "오늘",
            n=len(headlines[:20]),
            headlines=headlines_text,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=150,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content.strip()
            result = json.loads(content)

            score = float(result.get("score", 0.0))
            score = max(-1.0, min(1.0, score))
            reason = result.get("reason", "")

            self._cache[cache_key] = score
            return score, reason

        except Exception as e:
            logger.warning(f"GPT 감성분석 실패 {stock_code}: {e}")
            return 0.0, f"분석 실패: {e}"

    def analyze_batch(
        self,
        news_by_code: dict[str, list[str]],
        target_date: Optional[str] = None,
    ) -> dict[str, tuple[float, str]]:
        """여러 종목 감성분석 (순차 호출).

        Args:
            news_by_code: {code: [headline1, headline2, ...]}
            target_date: 날짜 문자열

        Returns:
            {code: (score, reason)}
        """
        results = {}
        for code, headlines in news_by_code.items():
            score, reason = self.analyze_headlines(
                headlines,
                stock_code=code,
                target_date=target_date,
            )
            results[code] = (score, reason)
        return results

    def clear_cache(self):
        """캐시 초기화."""
        self._cache.clear()
