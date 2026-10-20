"""
热力图可视化 - 用 Plotly 生成交互式图表
- 号码 × 时间窗口 的热度热力图
- 各号码热度排行
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
import numpy as np
import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = PROJECT_ROOT / "ui" / "static"


class HeatmapVisualizer:
    """热力图可视化器"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or UI_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render_heatmap(
        self,
        scores_matrix: np.ndarray,
        numbers: List[int],
        windows: List[int],
        title: str = "号码热度热力图",
        filename: str = "heatmap.html",
    ) -> Path:
        """
        scores_matrix: shape (n_windows, n_numbers) - 每个窗口对每个号码的综合热度
        numbers: 号码列表 [1, 2, ..., 35]
        windows: 窗口标签 ["30期", "100期", "500期", "全部"]
        """
        fig = go.Figure(data=go.Heatmap(
            z=scores_matrix,
            x=[str(n) for n in numbers],
            y=windows,
            colorscale=[
                [0.0, "#1e3a8a"],   # 冷（深蓝）
                [0.5, "#fbbf24"],   # 温（黄）
                [1.0, "#dc2626"],   # 热（红）
            ],
            zmin=0,
            zmax=1,
            colorbar=dict(
                title="热度",
                tickvals=[0, 0.25, 0.5, 0.75, 1.0],
                ticktext=["极冷", "冷", "温", "热", "极热"],
            ),
            hovertemplate="号码 %{x}<br>窗口: %{y}<br>热度: %{z:.3f}<extra></extra>",
        ))

        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=20)),
            xaxis_title="号码",
            yaxis_title="窗口",
            template="plotly_dark",
            height=400,
            width=1400,
        )

        out_path = self.output_dir / filename
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path

    def render_number_ranking(
        self,
        scores: np.ndarray,
        numbers: List[int],
        title: str = "号码热度排行榜",
        top_k: int = 35,
        filename: str = "ranking.html",
    ) -> Path:
        """号码热度排行榜（横向条形图）"""
        idx = np.argsort(scores)[::-1][:top_k]
        sorted_numbers = [numbers[i] for i in idx]
        sorted_scores = scores[idx]

        # 上色：热红、温黄、冷蓝
        colors = []
        for s in sorted_scores:
            if s >= 0.75:
                colors.append("#dc2626")
            elif s >= 0.45:
                colors.append("#fbbf24")
            else:
                colors.append("#1e3a8a")

        fig = go.Figure(data=go.Bar(
            x=sorted_scores,
            y=[f"号码 {n:02d}" for n in sorted_numbers],
            orientation="h",
            marker_color=colors,
            hovertemplate="<b>号码 %{y}</b><br>热度: %{x:.3f}<extra></extra>",
        ))

        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=20)),
            xaxis_title="热度评分",
            yaxis=dict(autorange="reversed"),
            template="plotly_dark",
            height=900,
            width=900,
        )

        out_path = self.output_dir / filename
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path

    def render_trend_chart(
        self,
        rolling_freq: Dict[int, np.ndarray],
        numbers: List[int],
        window: int = 30,
        title: str = "号码热度走势图",
        filename: str = "trend.html",
    ) -> Path:
        """
        走势图 - 每个号码的滚动频率曲线
        rolling_freq: {号码: 滚动频率数组}
        """
        fig = go.Figure()

        for num in numbers:
            if num in rolling_freq:
                data = rolling_freq[num]
                fig.add_trace(go.Scatter(
                    y=data,
                    mode="lines",
                    name=f"号码 {num:02d}",
                    line=dict(width=1.5),
                    opacity=0.7,
                    hovertemplate=f"号码 {num}<br>期数: %{{x}}<br>频率: %{{y:.3f}}<extra></extra>",
                ))

        fig.update_layout(
            title=dict(text=f"{title}（窗口={window}）", x=0.5, font=dict(size=20)),
            xaxis_title="期数（最近优先）",
            yaxis_title="滚动频率",
            template="plotly_dark",
            height=600,
            width=1400,
            hovermode="x unified",
        )

        out_path = self.output_dir / filename
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path

    def render_missing_chart(
        self,
        missing_values: np.ndarray,
        numbers: List[int],
        title: str = "号码遗漏值分布",
        filename: str = "missing.html",
    ) -> Path:
        """遗漏值柱状图"""
        # 按遗漏值排序
        idx = np.argsort(missing_values)[::-1]
        sorted_numbers = [numbers[i] for i in idx]
        sorted_missing = missing_values[idx]

        # 颜色映射
        max_miss = sorted_missing.max()
        colors = [f"rgb({int(255 * m / max_miss)}, {int(100 * (1 - m / max_miss))}, 50)" for m in sorted_missing]

        fig = go.Figure(data=go.Bar(
            x=[f"{n:02d}" for n in sorted_numbers],
            y=sorted_missing,
            marker_color=colors,
            hovertemplate="号码 %{x}<br>遗漏期数: %{y}<extra></extra>",
        ))

        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=20)),
            xaxis_title="号码",
            yaxis_title="遗漏期数",
            template="plotly_dark",
            height=500,
            width=1400,
        )

        out_path = self.output_dir / filename
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path

    def render_dashboard(
        self,
        front_scores: np.ndarray,
        back_scores: np.ndarray,
        config: Dict,
        extra_data: Dict = None,
        filename: str = "dashboard.html",
    ) -> Path:
        """
        综合仪表盘 - 单页 HTML，所有关键图表在一处
        """
        extra_data = extra_data or {}

        # 前区
        front_numbers = list(range(1, 36))
        back_numbers = list(range(1, 13))

        # 创建 2x2 子图布局
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "前区号码热度（35个号码）",
                "后区号码热度（12个号码）",
                "前区 Top 15 热号",
                "后区 Top 6 热号",
            ),
            specs=[[{"type": "bar"}, {"type": "bar"}],
                   [{"type": "bar"}, {"type": "bar"}]],
            vertical_spacing=0.15,
            horizontal_spacing=0.1,
        )

        # 前区全量热度
        front_colors = ["#dc2626" if s >= 0.75 else "#fbbf24" if s >= 0.45 else "#1e3a8a" for s in front_scores]
        fig.add_trace(go.Bar(
            x=[f"{n:02d}" for n in front_numbers],
            y=front_scores,
            marker_color=front_colors,
            name="前区热度",
            showlegend=False,
        ), row=1, col=1)

        # 后区全量热度
        back_colors = ["#dc2626" if s >= 0.75 else "#fbbf24" if s >= 0.45 else "#1e3a8a" for s in back_scores]
        fig.add_trace(go.Bar(
            x=[f"{n:02d}" for n in back_numbers],
            y=back_scores,
            marker_color=back_colors,
            name="后区热度",
            showlegend=False,
        ), row=1, col=2)

        # 前区 Top 15
        top15_front_idx = np.argsort(front_scores)[::-1][:15]
        fig.add_trace(go.Bar(
            x=[f"号 {front_numbers[i]}" for i in top15_front_idx],
            y=front_scores[top15_front_idx],
            marker_color="#dc2626",
            name="前区热号",
            showlegend=False,
        ), row=2, col=1)

        # 后区 Top 6
        top6_back_idx = np.argsort(back_scores)[::-1][:6]
        fig.add_trace(go.Bar(
            x=[f"号 {back_numbers[i]}" for i in top6_back_idx],
            y=back_scores[top6_back_idx],
            marker_color="#dc2626",
            name="后区热号",
            showlegend=False,
        ), row=2, col=2)

        fig.update_layout(
            title=dict(text="大乐透号码冷热度仪表盘", x=0.5, font=dict(size=24)),
            template="plotly_dark",
            height=900,
            width=1500,
        )
        fig.update_xaxes(title_text="号码", row=1, col=1)
        fig.update_xaxes(title_text="号码", row=1, col=2)
        fig.update_xaxes(title_text="号码", row=2, col=1)
        fig.update_xaxes(title_text="号码", row=2, col=2)
        fig.update_yaxes(title_text="热度", range=[0, 1], row=1, col=1)
        fig.update_yaxes(title_text="热度", range=[0, 1], row=1, col=2)
        fig.update_yaxes(title_text="热度", row=2, col=1)
        fig.update_yaxes(title_text="热度", row=2, col=2)

        out_path = self.output_dir / filename
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path
