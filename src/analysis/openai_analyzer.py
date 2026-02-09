"""OpenAI-powered strategy analysis module."""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StrategyAnalysis:
    """AI analysis result for a strategy."""

    strategy_name: str
    loss_reasons: list[str]
    common_patterns: list[str]
    parameter_recommendations: dict[str, Any]
    filter_recommendations: list[str]
    confidence_score: float
    raw_response: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "loss_reasons": self.loss_reasons,
            "common_patterns": self.common_patterns,
            "parameter_recommendations": self.parameter_recommendations,
            "filter_recommendations": self.filter_recommendations,
            "confidence_score": self.confidence_score,
        }


@dataclass
class TradeAnalysisData:
    """Trade data prepared for AI analysis."""

    strategy_name: str
    current_params: dict
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    total_return: float
    losing_trades_summary: list[dict] = field(default_factory=list)
    winning_trades_summary: list[dict] = field(default_factory=list)
    market_conditions: dict = field(default_factory=dict)


class OpenAIAnalyzer:
    """Analyzer using OpenAI GPT-4o for strategy optimization."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        """
        Initialize OpenAI analyzer.

        Args:
            api_key: OpenAI API key. Uses OPENAI_API_KEY env var if not provided.
            model: OpenAI model to use.
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment variable."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def analyze_strategy(self, data: TradeAnalysisData) -> StrategyAnalysis:
        """
        Analyze a strategy's performance using AI.

        Args:
            data: Trade analysis data for the strategy.

        Returns:
            StrategyAnalysis with recommendations.
        """
        prompt = self._build_analysis_prompt(data)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            raw_response = response.choices[0].message.content
            analysis = self._parse_response(data.strategy_name, raw_response)

            logger.info(f"Analysis completed for {data.strategy_name}")
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing {data.strategy_name}: {e}")
            raise

    def analyze_all_strategies(
        self, strategies_data: list[TradeAnalysisData]
    ) -> list[StrategyAnalysis]:
        """
        Analyze multiple strategies.

        Args:
            strategies_data: List of trade analysis data for each strategy.

        Returns:
            List of StrategyAnalysis results.
        """
        results = []
        for data in strategies_data:
            try:
                analysis = self.analyze_strategy(data)
                results.append(analysis)
            except Exception as e:
                logger.error(f"Failed to analyze {data.strategy_name}: {e}")

        return results

    def _get_system_prompt(self) -> str:
        """Get the system prompt for the AI."""
        return """당신은 15년 경력의 전문 퀀트 트레이더이자 알고리즘 트레이딩 전문가입니다.

당신의 임무는 백테스트 결과를 분석하고 전략 개선 방안을 제시하는 것입니다.

분석 시 다음 사항을 고려하세요:
1. 패배 거래의 공통적인 패턴과 시장 조건
2. 진입 시점의 기술적 지표 값과 타이밍
3. 손절/익절 수준의 적정성
4. 추가적인 필터 조건의 필요성
5. 파라미터 조정 방안

응답은 반드시 JSON 형식으로 제공해야 합니다:
{
    "loss_reasons": ["이유1", "이유2", ...],
    "common_patterns": ["패턴1", "패턴2", ...],
    "parameter_recommendations": {
        "param_name": {"current": 현재값, "recommended": 권장값, "reason": "이유"}
    },
    "filter_recommendations": ["필터1", "필터2", ...],
    "confidence_score": 0.0-1.0
}"""

    def _build_analysis_prompt(self, data: TradeAnalysisData) -> str:
        """Build the analysis prompt for a strategy."""
        losing_summary = self._format_trades_summary(data.losing_trades_summary[:20])
        winning_summary = self._format_trades_summary(data.winning_trades_summary[:10])

        prompt = f"""## 전략 분석 요청

### 전략 정보
- **전략명**: {data.strategy_name}
- **현재 파라미터**: {json.dumps(data.current_params, ensure_ascii=False, indent=2)}

### 성과 지표
- **승률**: {data.win_rate:.1f}%
- **총 거래 수**: {data.total_trades}
- **승리 거래**: {data.winning_trades}
- **패배 거래**: {data.losing_trades}
- **평균 수익**: {data.avg_win:.2%}
- **평균 손실**: {data.avg_loss:.2%}
- **총 수익률**: {data.total_return:.2%}

### 패배 거래 분석 (최근 20건)
{losing_summary}

### 승리 거래 분석 (최근 10건)
{winning_summary}

### 시장 상황 분석
{json.dumps(data.market_conditions, ensure_ascii=False, indent=2) if data.market_conditions else "데이터 없음"}

### 분석 요청사항
1. 이 전략이 손실을 보는 주요 원인은 무엇인가?
2. 패배 거래들의 공통적인 패턴은 무엇인가?
3. 구체적인 파라미터 개선 방안은?
4. 추가해야 할 필터 조건은?
5. 승률을 50% 이상으로 올리기 위한 핵심 개선 포인트는?

JSON 형식으로 응답해주세요."""

        return prompt

    def _format_trades_summary(self, trades: list[dict]) -> str:
        """Format trades summary for prompt."""
        if not trades:
            return "데이터 없음"

        lines = []
        for i, trade in enumerate(trades, 1):
            lines.append(
                f"{i}. 종목: {trade.get('code', 'N/A')}, "
                f"진입가: {trade.get('entry_price', 0):,}, "
                f"청산가: {trade.get('exit_price', 0):,}, "
                f"수익률: {trade.get('pnl_rate', 0):.2%}, "
                f"보유일: {trade.get('holding_days', 0)}일, "
                f"진입사유: {trade.get('entry_reason', 'N/A')}, "
                f"청산사유: {trade.get('exit_reason', 'N/A')}"
            )
            if trade.get("indicators"):
                lines.append(f"   지표: {trade['indicators']}")

        return "\n".join(lines)

    def _parse_response(self, strategy_name: str, raw_response: str) -> StrategyAnalysis:
        """Parse the AI response into StrategyAnalysis."""
        try:
            parsed = json.loads(raw_response)

            return StrategyAnalysis(
                strategy_name=strategy_name,
                loss_reasons=parsed.get("loss_reasons", []),
                common_patterns=parsed.get("common_patterns", []),
                parameter_recommendations=parsed.get("parameter_recommendations", {}),
                filter_recommendations=parsed.get("filter_recommendations", []),
                confidence_score=parsed.get("confidence_score", 0.5),
                raw_response=raw_response,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return StrategyAnalysis(
                strategy_name=strategy_name,
                loss_reasons=[],
                common_patterns=[],
                parameter_recommendations={},
                filter_recommendations=[],
                confidence_score=0.0,
                raw_response=raw_response,
            )

    def get_optimization_summary(
        self, analyses: list[StrategyAnalysis]
    ) -> dict:
        """
        Generate a summary of all optimization recommendations.

        Args:
            analyses: List of strategy analyses.

        Returns:
            Summary dictionary with prioritized recommendations.
        """
        summary = {
            "total_strategies": len(analyses),
            "high_confidence_count": sum(
                1 for a in analyses if a.confidence_score >= 0.7
            ),
            "strategies": {},
            "common_issues": [],
        }

        all_issues = []
        for analysis in analyses:
            summary["strategies"][analysis.strategy_name] = {
                "confidence": analysis.confidence_score,
                "top_issues": analysis.loss_reasons[:3],
                "key_recommendations": list(analysis.parameter_recommendations.keys()),
            }
            all_issues.extend(analysis.loss_reasons)

        issue_counts = {}
        for issue in all_issues:
            issue_lower = issue.lower()
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        summary["common_issues"] = sorted(
            issue_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        return summary
