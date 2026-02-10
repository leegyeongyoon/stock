"""OpenAI-powered strategy code analysis module."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 전략명 -> 파일 경로 매핑 (data-driven strategies)
STRATEGY_FILE_MAP = {
    # Data-driven intraday strategies will be added here after Phase 2/3
}


@dataclass
class CodeAnalysisResult:
    """AI code analysis result."""

    strategy_name: str
    core_issues: list[str]
    code_problems: list[dict]  # {"line": str, "problem": str, "suggestion": str}
    parameter_changes: dict[str, dict]  # {"param": {"current": x, "recommended": y, "reason": str}}
    new_filters: list[str]
    expected_improvement: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "core_issues": self.core_issues,
            "code_problems": self.code_problems,
            "parameter_changes": self.parameter_changes,
            "new_filters": self.new_filters,
            "expected_improvement": self.expected_improvement,
            "confidence": self.confidence,
        }


class StrategyCodeAnalyzer:
    """Analyzer that sends actual strategy code to GPT-4o."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.base_path = Path(__file__).parent.parent.parent

    def get_strategy_code(self, strategy_name: str) -> str:
        """Read the actual strategy code file."""
        if strategy_name not in STRATEGY_FILE_MAP:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        file_path = self.base_path / STRATEGY_FILE_MAP[strategy_name]

        if not file_path.exists():
            raise FileNotFoundError(f"Strategy file not found: {file_path}")

        return file_path.read_text(encoding="utf-8")

    def analyze_strategy_code(
        self,
        strategy_name: str,
        backtest_results: dict,
        losing_trades: list[dict] = None,
        winning_trades: list[dict] = None,
    ) -> CodeAnalysisResult:
        """
        Analyze strategy code with GPT-4o.

        Args:
            strategy_name: Name of the strategy
            backtest_results: Backtest metrics (win_rate, total_return, etc.)
            losing_trades: Sample of losing trades
            winning_trades: Sample of winning trades
        """
        # Get actual code
        code = self.get_strategy_code(strategy_name)

        # Build prompt with code
        prompt = self._build_code_analysis_prompt(
            strategy_name, code, backtest_results, losing_trades, winning_trades
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            return self._parse_response(strategy_name, raw)

        except Exception as e:
            logger.error(f"Error analyzing {strategy_name}: {e}")
            raise

    def _get_system_prompt(self) -> str:
        return """당신은 20년 경력의 퀀트 개발자이자 알고리즘 트레이딩 전문가입니다.

당신의 임무는 **실제 전략 코드**를 분석하고, 코드 수준에서 구체적인 개선 방안을 제시하는 것입니다.

분석 시 반드시 다음을 수행하세요:
1. generate_signals() 함수의 각 조건을 하나씩 검토
2. 어떤 조건이 잘못된 신호를 발생시키는지 식별
3. should_exit() 함수의 청산 로직 검토
4. 파라미터 값이 적절한지 검토
5. 누락된 필터나 조건 식별

응답은 반드시 다음 JSON 형식으로:
{
    "core_issues": ["핵심 문제 1", "핵심 문제 2", ...],
    "code_problems": [
        {
            "location": "조건/라인 설명",
            "problem": "문제점",
            "suggestion": "수정 방안"
        }
    ],
    "parameter_changes": {
        "파라미터명": {
            "current": 현재값,
            "recommended": 권장값,
            "reason": "변경 이유",
            "expected_impact": "예상 영향"
        }
    },
    "new_filters": ["추가할 필터 1", "추가할 필터 2"],
    "expected_improvement": "예상 개선 효과 설명",
    "confidence": 0.0-1.0
}"""

    def _build_code_analysis_prompt(
        self,
        strategy_name: str,
        code: str,
        results: dict,
        losing_trades: list[dict] = None,
        winning_trades: list[dict] = None,
    ) -> str:
        losing_summary = self._format_trades(losing_trades[:15] if losing_trades else [])
        winning_summary = self._format_trades(winning_trades[:10] if winning_trades else [])

        return f"""## 전략 코드 분석 요청

### 전략명: {strategy_name}

### 백테스트 성과
- 승률: {results.get('win_rate', 0):.1f}%
- 총 수익률: {results.get('total_return', 0):.2f}%
- 총 거래 수: {results.get('total_trades', 0)}
- 승리 거래: {results.get('winning_trades', 0)}
- 패배 거래: {results.get('losing_trades', 0)}
- 평균 수익: {results.get('avg_win', 0):.2f}%
- 평균 손실: {results.get('avg_loss', 0):.2f}%
- 손익비(Profit Factor): {results.get('profit_factor', 0):.2f}
- 최대 낙폭: {results.get('max_drawdown', 0):.2f}%
- 샤프 비율: {results.get('sharpe_ratio', 0):.2f}

### 전략 코드 (전체)
```python
{code}
```

### 패배 거래 샘플 (최근 15건)
{losing_summary}

### 승리 거래 샘플 (최근 10건)
{winning_summary}

### 분석 요청
1. **코드의 어떤 조건이 잘못된 신호를 만드는가?**
   - generate_signals()의 각 조건을 검토하고, 문제가 되는 부분을 구체적으로 지적해주세요.

2. **파라미터 값이 적절한가?**
   - 현재 기본값들이 한국 주식 시장에 적합한지 분석해주세요.
   - 변경이 필요한 파라미터와 그 이유를 설명해주세요.

3. **어떤 필터가 추가되어야 하는가?**
   - 현재 조건에서 누락된 중요한 필터가 있다면 제안해주세요.

4. **청산 로직(should_exit)에 문제가 있는가?**

JSON 형식으로 응답해주세요."""

    def _format_trades(self, trades: list[dict]) -> str:
        if not trades:
            return "데이터 없음"

        lines = []
        for i, t in enumerate(trades, 1):
            lines.append(
                f"{i}. 종목: {t.get('code', 'N/A')}, "
                f"수익률: {t.get('pnl_rate', 0):.2%}, "
                f"보유일: {t.get('holding_days', 0)}일, "
                f"진입: {t.get('entry_reason', 'N/A')}, "
                f"청산: {t.get('exit_reason', 'N/A')}"
            )
        return "\n".join(lines)

    def _parse_response(self, strategy_name: str, raw: str) -> CodeAnalysisResult:
        try:
            data = json.loads(raw)
            return CodeAnalysisResult(
                strategy_name=strategy_name,
                core_issues=data.get("core_issues", []),
                code_problems=data.get("code_problems", []),
                parameter_changes=data.get("parameter_changes", {}),
                new_filters=data.get("new_filters", []),
                expected_improvement=data.get("expected_improvement", ""),
                confidence=data.get("confidence", 0.5),
            )
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse response for {strategy_name}")
            return CodeAnalysisResult(
                strategy_name=strategy_name,
                core_issues=[],
                code_problems=[],
                parameter_changes={},
                new_filters=[],
                expected_improvement="",
                confidence=0.0,
            )
