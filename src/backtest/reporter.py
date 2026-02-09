"""Backtest report generation."""

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtest.metrics import BacktestMetrics
from src.utils.helpers import format_currency, format_percent


class BacktestReporter:
    """Generate backtest reports and visualizations."""

    def __init__(self, output_dir: str = "reports"):
        """
        Initialize reporter.

        Args:
            output_dir: Directory to save reports.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_summary(self, metrics: BacktestMetrics) -> str:
        """Generate text summary of backtest results."""
        summary = f"""
{'='*60}
백테스트 결과 요약: {metrics.strategy_name}
{'='*60}

기간: {metrics.start_date} ~ {metrics.end_date}
초기 자본금: {format_currency(metrics.initial_capital)}
최종 자본금: {format_currency(metrics.final_capital)}

수익률 지표:
  - 총 수익률: {format_percent(metrics.total_return)}
  - 연평균 수익률 (CAGR): {format_percent(metrics.cagr)}
  - 변동성 (연환산): {format_percent(metrics.volatility)}

위험 지표:
  - 샤프 비율: {metrics.sharpe_ratio:.2f}
  - 소르티노 비율: {metrics.sortino_ratio:.2f}
  - 최대 낙폭 (MDD): {format_percent(metrics.max_drawdown)}
  - MDD 지속 기간: {metrics.max_drawdown_duration}일

거래 통계:
  - 총 거래 횟수: {metrics.total_trades}
  - 승리 거래: {metrics.winning_trades}
  - 패배 거래: {metrics.losing_trades}
  - 승률: {format_percent(metrics.win_rate)}
  - 손익비 (Profit Factor): {metrics.profit_factor:.2f}
  - 평균 수익 (승리 시): {format_percent(metrics.avg_win)}
  - 평균 손실 (패배 시): {format_percent(metrics.avg_loss)}
  - 평균 거래 수익률: {format_percent(metrics.avg_trade_return)}
  - 평균 보유 기간: {metrics.avg_holding_days:.1f}일

{'='*60}
"""
        return summary

    def generate_comparison_table(
        self,
        results: dict[str, BacktestMetrics],
    ) -> pd.DataFrame:
        """Generate comparison table for multiple strategies."""
        data = []
        for name, metrics in results.items():
            data.append({
                "전략": name,
                "총수익률": f"{metrics.total_return:.1%}",
                "CAGR": f"{metrics.cagr:.1%}",
                "샤프비율": f"{metrics.sharpe_ratio:.2f}",
                "MDD": f"{metrics.max_drawdown:.1%}",
                "승률": f"{metrics.win_rate:.1%}",
                "손익비": f"{metrics.profit_factor:.2f}",
                "거래횟수": metrics.total_trades,
                "평균수익률": f"{metrics.avg_trade_return:.2%}",
            })

        df = pd.DataFrame(data)
        return df.sort_values("총수익률", ascending=False)

    def plot_equity_curve(
        self,
        metrics: BacktestMetrics,
        equity_curve: Optional[pd.Series] = None,
        save: bool = True,
    ) -> go.Figure:
        """Plot equity curve."""
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            row_heights=[0.7, 0.3],
            subplot_titles=("자산 곡선", "일별 수익률"),
        )

        # Equity curve (if provided, otherwise use cumulative returns)
        if equity_curve is not None:
            fig.add_trace(
                go.Scatter(
                    x=equity_curve.index,
                    y=equity_curve.values,
                    name="자산",
                    line=dict(color="blue"),
                ),
                row=1, col=1,
            )
        elif metrics.daily_returns:
            cumulative = [metrics.initial_capital]
            for r in metrics.daily_returns:
                cumulative.append(cumulative[-1] * (1 + r))
            fig.add_trace(
                go.Scatter(
                    y=cumulative,
                    name="자산",
                    line=dict(color="blue"),
                ),
                row=1, col=1,
            )

        # Daily returns
        if metrics.daily_returns:
            colors = ["green" if r >= 0 else "red" for r in metrics.daily_returns]
            fig.add_trace(
                go.Bar(
                    y=metrics.daily_returns,
                    name="일별 수익률",
                    marker_color=colors,
                ),
                row=2, col=1,
            )

        fig.update_layout(
            title=f"{metrics.strategy_name} 백테스트 결과",
            height=600,
            showlegend=True,
        )

        fig.update_yaxes(title_text="자산 (원)", row=1, col=1)
        fig.update_yaxes(title_text="수익률 (%)", tickformat=".1%", row=2, col=1)

        if save:
            filename = self.output_dir / f"{metrics.strategy_name}_equity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            fig.write_html(str(filename))

        return fig

    def plot_monthly_returns_heatmap(
        self,
        metrics: BacktestMetrics,
        save: bool = True,
    ) -> go.Figure:
        """Plot monthly returns heatmap."""
        if not metrics.monthly_returns:
            return go.Figure()

        # Parse monthly returns
        data = []
        for month_key, return_val in metrics.monthly_returns.items():
            year, month = month_key.split("-")
            data.append({
                "year": int(year),
                "month": int(month),
                "return": return_val,
            })

        df = pd.DataFrame(data)
        if df.empty:
            return go.Figure()

        # Pivot for heatmap
        pivot = df.pivot(index="year", columns="month", values="return")
        pivot.columns = ["1월", "2월", "3월", "4월", "5월", "6월",
                        "7월", "8월", "9월", "10월", "11월", "12월"][:len(pivot.columns)]

        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale="RdYlGn",
            zmid=0,
            text=[[f"{v:.1%}" if not pd.isna(v) else "" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont={"size": 10},
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Return: %{z:.2%}<extra></extra>",
        ))

        fig.update_layout(
            title=f"{metrics.strategy_name} 월별 수익률",
            xaxis_title="월",
            yaxis_title="연도",
            height=400,
        )

        if save:
            filename = self.output_dir / f"{metrics.strategy_name}_monthly_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            fig.write_html(str(filename))

        return fig

    def plot_comparison(
        self,
        results: dict[str, BacktestMetrics],
        save: bool = True,
    ) -> go.Figure:
        """Plot strategy comparison chart."""
        strategies = list(results.keys())

        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("총 수익률", "샤프 비율", "최대 낙폭", "승률"),
        )

        # Total return
        returns = [results[s].total_return for s in strategies]
        colors = ["green" if r >= 0 else "red" for r in returns]
        fig.add_trace(
            go.Bar(x=strategies, y=returns, marker_color=colors, name="수익률"),
            row=1, col=1,
        )

        # Sharpe ratio
        sharpe = [results[s].sharpe_ratio for s in strategies]
        fig.add_trace(
            go.Bar(x=strategies, y=sharpe, marker_color="blue", name="샤프"),
            row=1, col=2,
        )

        # Max drawdown
        mdd = [results[s].max_drawdown for s in strategies]
        fig.add_trace(
            go.Bar(x=strategies, y=mdd, marker_color="red", name="MDD"),
            row=2, col=1,
        )

        # Win rate
        winrate = [results[s].win_rate for s in strategies]
        fig.add_trace(
            go.Bar(x=strategies, y=winrate, marker_color="green", name="승률"),
            row=2, col=2,
        )

        fig.update_layout(
            title="전략 비교",
            height=600,
            showlegend=False,
        )

        fig.update_yaxes(tickformat=".1%", row=1, col=1)
        fig.update_yaxes(tickformat=".1%", row=2, col=1)
        fig.update_yaxes(tickformat=".1%", row=2, col=2)

        if save:
            filename = self.output_dir / f"strategy_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            fig.write_html(str(filename))

        return fig

    def generate_full_report(
        self,
        results: dict[str, BacktestMetrics],
        save: bool = True,
    ) -> str:
        """Generate full HTML report with all charts and tables."""
        html_parts = [
            "<html><head>",
            "<meta charset='utf-8'>",
            "<title>백테스트 리포트</title>",
            "<style>",
            "body { font-family: 'Malgun Gothic', sans-serif; margin: 20px; }",
            "table { border-collapse: collapse; width: 100%; margin: 20px 0; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: right; }",
            "th { background-color: #4CAF50; color: white; }",
            "tr:nth-child(even) { background-color: #f2f2f2; }",
            "h1, h2 { color: #333; }",
            ".metric-box { display: inline-block; padding: 15px; margin: 10px; ",
            "background: #f5f5f5; border-radius: 8px; }",
            ".positive { color: green; }",
            ".negative { color: red; }",
            "</style>",
            "</head><body>",
            f"<h1>백테스트 리포트</h1>",
            f"<p>생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        ]

        # Comparison table
        comparison_df = self.generate_comparison_table(results)
        html_parts.append("<h2>전략 비교</h2>")
        html_parts.append(comparison_df.to_html(index=False, classes="comparison-table"))

        # Individual strategy summaries
        for name, metrics in results.items():
            html_parts.append(f"<h2>{name}</h2>")
            html_parts.append(f"<pre>{self.generate_summary(metrics)}</pre>")

        html_parts.append("</body></html>")

        html_content = "\n".join(html_parts)

        if save:
            filename = self.output_dir / f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)

        return html_content
