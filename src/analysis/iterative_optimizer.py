"""Iterative optimization system with feedback loops."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from src.analysis.code_analyzer import StrategyCodeAnalyzer, STRATEGY_FILE_MAP
from src.analysis.parameter_tester import ParameterTester, get_strategy_class
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IterationResult:
    """Result of a single optimization iteration."""

    iteration: int
    strategy_name: str
    previous_win_rate: float
    previous_return: float
    new_win_rate: float
    new_return: float
    changes_tested: list[dict]
    changes_applied: list[dict]
    feedback_sent: str
    ai_response_summary: str

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "strategy_name": self.strategy_name,
            "previous_win_rate": round(self.previous_win_rate, 2),
            "previous_return": round(self.previous_return, 2),
            "new_win_rate": round(self.new_win_rate, 2),
            "new_return": round(self.new_return, 2),
            "win_rate_change": round(self.new_win_rate - self.previous_win_rate, 2),
            "return_change": round(self.new_return - self.previous_return, 2),
            "changes_tested": self.changes_tested,
            "changes_applied": self.changes_applied,
            "improved": self.new_return > self.previous_return,
        }


@dataclass
class StrategyProgress:
    """Track optimization progress for a strategy."""

    strategy_name: str
    initial_win_rate: float
    initial_return: float
    current_win_rate: float
    current_return: float
    current_params: dict
    iteration_history: list[IterationResult] = field(default_factory=list)
    failed_recommendations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "initial_win_rate": round(self.initial_win_rate, 2),
            "initial_return": round(self.initial_return, 2),
            "current_win_rate": round(self.current_win_rate, 2),
            "current_return": round(self.current_return, 2),
            "total_improvement": round(self.current_return - self.initial_return, 2),
            "win_rate_improvement": round(self.current_win_rate - self.initial_win_rate, 2),
            "current_params": self.current_params,
            "iterations_completed": len(self.iteration_history),
            "failed_recommendations": self.failed_recommendations,
        }


class IterativeOptimizer:
    """Iteratively optimize strategies with AI feedback loops."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        sample_size: int = 50,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.code_analyzer = StrategyCodeAnalyzer(api_key=self.api_key, model=model)
        self.tester = ParameterTester(sample_size=sample_size)
        self.base_path = Path(__file__).parent.parent.parent
        self.reports_path = self.base_path / "reports"
        self.reports_path.mkdir(exist_ok=True)

    def update_strategy_code(
        self,
        strategy_name: str,
        param_name: str,
        old_value: Any,
        new_value: Any,
    ) -> bool:
        """Update actual strategy code file with new parameter value."""
        import re

        file_path = self.base_path / STRATEGY_FILE_MAP.get(strategy_name, "")
        if not file_path.exists():
            logger.error(f"Strategy file not found: {file_path}")
            return False

        try:
            code = file_path.read_text(encoding="utf-8")

            # Find and replace the default parameter value in __init__
            # Pattern: param_name: type = old_value
            if isinstance(old_value, bool):
                old_str = str(old_value)
                new_str = str(new_value)
            elif isinstance(old_value, float):
                old_str = str(old_value)
                new_str = str(new_value)
            elif isinstance(old_value, int):
                old_str = str(old_value)
                new_str = str(new_value)
            else:
                old_str = repr(old_value)
                new_str = repr(new_value)

            # Pattern to match parameter definition
            pattern = rf"({param_name}\s*:\s*\w+\s*=\s*){re.escape(old_str)}"
            replacement = rf"\g<1>{new_str}"

            new_code, count = re.subn(pattern, replacement, code)

            if count > 0:
                file_path.write_text(new_code, encoding="utf-8")
                logger.info(f"✅ Updated {strategy_name}: {param_name} = {old_value} → {new_value}")
                return True
            else:
                logger.warning(f"Could not find {param_name}={old_value} in {strategy_name}")
                return False

        except Exception as e:
            logger.error(f"Error updating {strategy_name}: {e}")
            return False

    def get_strategy_code(self, strategy_name: str) -> str:
        """Read the actual strategy code file."""
        return self.code_analyzer.get_strategy_code(strategy_name)

    def get_current_params(self, strategy_name: str) -> dict:
        """Extract current default parameters from strategy code."""
        code = self.get_strategy_code(strategy_name)
        params = {}

        # Parse __init__ to extract default parameters
        import re

        init_match = re.search(r"def __init__\s*\([^)]+\)", code, re.DOTALL)
        if init_match:
            init_str = init_match.group(0)
            # Find parameter=default patterns
            param_pattern = r"(\w+)\s*:\s*\w+\s*=\s*([^,\)]+)"
            for match in re.finditer(param_pattern, init_str):
                param_name = match.group(1)
                default_value = match.group(2).strip()
                # Convert to proper type
                try:
                    if default_value.lower() == "true":
                        params[param_name] = True
                    elif default_value.lower() == "false":
                        params[param_name] = False
                    elif "." in default_value:
                        params[param_name] = float(default_value)
                    else:
                        params[param_name] = int(default_value)
                except ValueError:
                    params[param_name] = default_value

        return params

    def _build_feedback_prompt(
        self,
        strategy_name: str,
        code: str,
        current_results: dict,
        progress: StrategyProgress,
        iteration: int,
    ) -> str:
        """Build prompt with feedback about what worked and what didn't."""
        # Build history summary
        history_lines = []
        for prev_iter in progress.iteration_history:
            changes_summary = ", ".join(
                [f"{c['param']}={c['value']}" for c in prev_iter.changes_applied]
            ) or "없음"
            history_lines.append(
                f"- Iteration {prev_iter.iteration}: "
                f"승률 {prev_iter.previous_win_rate:.1f}%→{prev_iter.new_win_rate:.1f}%, "
                f"수익률 {prev_iter.previous_return:.2f}%→{prev_iter.new_return:.2f}%, "
                f"적용된 변경: {changes_summary}"
            )

        history_summary = "\n".join(history_lines) if history_lines else "첫 번째 반복입니다."

        # Build failed recommendations summary
        failed_lines = []
        for failed in progress.failed_recommendations[-10:]:  # Last 10 failures
            failed_lines.append(
                f"- {failed['param']}: {failed['from']} → {failed['to']} "
                f"(결과: 승률 {failed['win_rate_change']:+.1f}%, 수익률 {failed['return_change']:+.2f}%)"
            )
        failed_summary = "\n".join(failed_lines) if failed_lines else "없음"

        # Determine if strategy is improving or not
        if progress.current_return > progress.initial_return:
            status = "개선됨"
            instruction = """이 전략은 개선되고 있습니다. 더 나은 성과를 위해:
1. 현재 적용된 개선 방향을 유지하면서 추가 최적화
2. 아직 테스트하지 않은 다른 파라미터 검토
3. 더 강한 필터 조건 추가 검토"""
        else:
            status = "개선 필요"
            instruction = """이 전략은 아직 개선이 필요합니다. 다른 접근 방식을 시도해주세요:
1. 이전에 실패한 추천들을 피하고 완전히 다른 방향 제안
2. 기존 조건의 강화/완화 대신 새로운 필터 추가 고려
3. 진입/청산 로직의 근본적인 개선 검토"""

        return f"""## 반복 최적화 요청 - Iteration {iteration}

### 전략명: {strategy_name}
### 현재 상태: {status}

### 현재 백테스트 성과
- 승률: {current_results.get('win_rate', 0):.1f}%
- 총 수익률: {current_results.get('total_return', 0):.2f}%
- 총 거래 수: {current_results.get('total_trades', 0)}
- 손익비: {current_results.get('profit_factor', 0):.2f}
- 샤프 비율: {current_results.get('sharpe_ratio', 0):.2f}

### 초기 대비 변화
- 초기 승률: {progress.initial_win_rate:.1f}% → 현재: {progress.current_win_rate:.1f}% ({progress.current_win_rate - progress.initial_win_rate:+.1f}%)
- 초기 수익률: {progress.initial_return:.2f}% → 현재: {progress.current_return:.2f}% ({progress.current_return - progress.initial_return:+.2f}%)

### 현재 파라미터
{json.dumps(progress.current_params, indent=2)}

### 이전 반복 이력
{history_summary}

### 실패한 추천들 (이것들은 피해주세요)
{failed_summary}

### 전략 코드 (전체)
```python
{code}
```

### 요청사항
{instruction}

**중요**:
- 이전에 실패한 파라미터 변경은 다시 추천하지 마세요
- 파라미터 값은 구체적인 숫자로 제시해주세요
- 각 추천에 대해 왜 이것이 효과가 있을지 설명해주세요

JSON 형식으로 응답해주세요."""

    def _get_feedback_system_prompt(self) -> str:
        return """당신은 20년 경력의 퀀트 개발자이자 알고리즘 트레이딩 전문가입니다.

당신의 임무는 이전 시도의 결과를 분석하고, **새로운 개선 방안**을 제시하는 것입니다.

핵심 원칙:
1. **실패한 추천을 반복하지 마세요** - 이미 테스트하고 실패한 파라미터 변경은 피하세요
2. **구체적인 값을 제시하세요** - "약간 높게" 대신 "0.03에서 0.035로"
3. **작은 변화부터 시도하세요** - 급격한 변화보다 점진적 개선이 안전합니다
4. **다양한 접근을 시도하세요** - 같은 파라미터만 조정하지 말고 다른 파라미터도 검토하세요

응답은 반드시 다음 JSON 형식으로:
{
    "analysis": "현재 상태에 대한 분석",
    "parameter_changes": {
        "파라미터명": {
            "current": 현재값,
            "recommended": 권장값,
            "reason": "변경 이유",
            "expected_impact": "예상 영향"
        }
    },
    "new_filters": ["추가할 필터 설명"],
    "alternative_approach": "만약 파라미터 변경이 효과가 없다면 시도할 대안",
    "confidence": 0.0-1.0
}"""

    def analyze_with_feedback(
        self,
        strategy_name: str,
        current_results: dict,
        progress: StrategyProgress,
        iteration: int,
    ) -> dict:
        """Analyze strategy with feedback about previous attempts."""
        code = self.get_strategy_code(strategy_name)
        prompt = self._build_feedback_prompt(
            strategy_name, code, current_results, progress, iteration
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_feedback_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            return json.loads(raw)

        except Exception as e:
            logger.error(f"Error analyzing {strategy_name}: {e}")
            return {"parameter_changes": {}, "new_filters": [], "confidence": 0}

    def run_iteration(
        self,
        strategy_name: str,
        progress: StrategyProgress,
        iteration: int,
    ) -> IterationResult:
        """Run a single optimization iteration for a strategy."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Iteration {iteration} for {strategy_name}")
        logger.info(f"{'='*60}")

        # Get current backtest results
        strategy_class = get_strategy_class(strategy_name)
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        # Run backtest with current params
        current_strategy = strategy_class(**progress.current_params)
        current_results = self.tester.run_single_strategy_backtest(current_strategy)

        # Update progress with current results
        progress.current_win_rate = current_results["win_rate"]
        progress.current_return = current_results["total_return"]

        # Get AI analysis with feedback
        logger.info(f"Requesting AI analysis with feedback...")
        ai_response = self.analyze_with_feedback(
            strategy_name, current_results, progress, iteration
        )

        # Test each recommended parameter change
        changes_tested = []
        changes_applied = []
        param_changes = ai_response.get("parameter_changes", {})

        for param_name, change_info in param_changes.items():
            current_val = change_info.get("current")
            recommended_val = change_info.get("recommended")

            if current_val is None or recommended_val is None:
                continue

            # Skip if this exact change was already tested and failed
            already_failed = any(
                f["param"] == param_name and f["to"] == recommended_val
                for f in progress.failed_recommendations
            )
            if already_failed:
                logger.info(f"Skipping {param_name}={recommended_val} (already failed)")
                continue

            logger.info(f"Testing {param_name}: {current_val} → {recommended_val}")

            # Test the change
            test_result = self.tester.test_parameter_change(
                strategy_class,
                param_name,
                current_val,
                recommended_val,
                {k: v for k, v in progress.current_params.items() if k != param_name},
            )

            changes_tested.append({
                "param": param_name,
                "from": current_val,
                "to": recommended_val,
                "improved": test_result.improved,
                "win_rate_change": test_result.new_win_rate - test_result.original_win_rate,
                "return_change": test_result.new_return - test_result.original_return,
            })

            if test_result.improved:
                logger.info(f"✅ {param_name} improved! Applying change.")
                changes_applied.append({
                    "param": param_name,
                    "value": recommended_val,
                    "win_rate_change": test_result.new_win_rate - test_result.original_win_rate,
                    "return_change": test_result.new_return - test_result.original_return,
                })
                # Update current params
                progress.current_params[param_name] = recommended_val
                # Update actual strategy code file
                self.update_strategy_code(strategy_name, param_name, current_val, recommended_val)
            else:
                logger.info(f"❌ {param_name} did not improve. Recording as failed.")
                progress.failed_recommendations.append({
                    "param": param_name,
                    "from": current_val,
                    "to": recommended_val,
                    "win_rate_change": test_result.new_win_rate - test_result.original_win_rate,
                    "return_change": test_result.new_return - test_result.original_return,
                    "iteration": iteration,
                })

        # Run final backtest with all applied changes
        if changes_applied:
            final_strategy = strategy_class(**progress.current_params)
            final_results = self.tester.run_single_strategy_backtest(final_strategy)
            new_win_rate = final_results["win_rate"]
            new_return = final_results["total_return"]
        else:
            new_win_rate = progress.current_win_rate
            new_return = progress.current_return

        result = IterationResult(
            iteration=iteration,
            strategy_name=strategy_name,
            previous_win_rate=progress.current_win_rate,
            previous_return=progress.current_return,
            new_win_rate=new_win_rate,
            new_return=new_return,
            changes_tested=changes_tested,
            changes_applied=changes_applied,
            feedback_sent=f"Iteration {iteration}: {len(progress.failed_recommendations)} failed recommendations",
            ai_response_summary=ai_response.get("analysis", ""),
        )

        # Update progress
        progress.current_win_rate = new_win_rate
        progress.current_return = new_return
        progress.iteration_history.append(result)

        return result

    def optimize_strategy(
        self,
        strategy_name: str,
        initial_results: dict,
        num_iterations: int = 5,
    ) -> StrategyProgress:
        """Run multiple optimization iterations for a strategy."""
        logger.info(f"\n{'#'*60}")
        logger.info(f"Starting iterative optimization for {strategy_name}")
        logger.info(f"Initial: win_rate={initial_results['win_rate']:.1f}%, "
                   f"return={initial_results['total_return']:.2f}%")
        logger.info(f"{'#'*60}")

        # Initialize progress
        current_params = self.get_current_params(strategy_name)
        progress = StrategyProgress(
            strategy_name=strategy_name,
            initial_win_rate=initial_results["win_rate"],
            initial_return=initial_results["total_return"],
            current_win_rate=initial_results["win_rate"],
            current_return=initial_results["total_return"],
            current_params=current_params,
        )

        # Run iterations
        for i in range(1, num_iterations + 1):
            try:
                self.run_iteration(strategy_name, progress, i)

                # Log progress
                logger.info(f"\nAfter iteration {i}:")
                logger.info(f"  Win rate: {progress.initial_win_rate:.1f}% → {progress.current_win_rate:.1f}%")
                logger.info(f"  Return: {progress.initial_return:.2f}% → {progress.current_return:.2f}%")

            except Exception as e:
                logger.error(f"Error in iteration {i} for {strategy_name}: {e}")
                continue

        return progress

    def optimize_all_strategies(
        self,
        initial_report: dict,
        num_iterations: int = 5,
    ) -> dict[str, StrategyProgress]:
        """Optimize all strategies iteratively."""
        all_progress = {}

        for strategy_name, results in initial_report.items():
            initial_results = {
                "win_rate": results.get("optimized_win_rate", results.get("original_win_rate", 0)),
                "total_return": results.get("optimized_return", results.get("original_return", 0)),
                "total_trades": results.get("total_trades", 0),
            }

            progress = self.optimize_strategy(
                strategy_name, initial_results, num_iterations
            )
            all_progress[strategy_name] = progress

            # Save intermediate results
            self._save_progress(all_progress)

        return all_progress

    def _save_progress(self, all_progress: dict[str, StrategyProgress]) -> None:
        """Save current progress to file."""
        output = {
            name: progress.to_dict()
            for name, progress in all_progress.items()
        }

        output_file = self.reports_path / "iterative_optimization_progress.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

    def generate_final_report(
        self,
        all_progress: dict[str, StrategyProgress],
    ) -> dict:
        """Generate final optimization report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_iterations": 5,
            "strategies": {},
            "summary": {
                "total_initial_return": 0,
                "total_final_return": 0,
                "strategies_improved": 0,
                "total_strategies": len(all_progress),
            },
        }

        for name, progress in all_progress.items():
            report["strategies"][name] = progress.to_dict()
            report["summary"]["total_initial_return"] += progress.initial_return
            report["summary"]["total_final_return"] += progress.current_return
            if progress.current_return > progress.initial_return:
                report["summary"]["strategies_improved"] += 1

        report["summary"]["total_improvement"] = (
            report["summary"]["total_final_return"] -
            report["summary"]["total_initial_return"]
        )

        # Save report
        output_file = self.reports_path / "iterative_optimization_final.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"\nFinal report saved to {output_file}")
        return report


def run_iterative_optimization(num_iterations: int = 5, sample_size: int = 50):
    """Main function to run iterative optimization."""
    # Load current optimization report
    reports_path = Path(__file__).parent.parent.parent / "reports"
    report_file = reports_path / "final_optimization_report.json"

    if not report_file.exists():
        raise FileNotFoundError(f"Report not found: {report_file}")

    with open(report_file, "r", encoding="utf-8") as f:
        initial_report = json.load(f)

    # Run optimization
    optimizer = IterativeOptimizer(sample_size=sample_size)
    all_progress = optimizer.optimize_all_strategies(initial_report, num_iterations)

    # Generate final report
    final_report = optimizer.generate_final_report(all_progress)

    return final_report


if __name__ == "__main__":
    run_iterative_optimization()
