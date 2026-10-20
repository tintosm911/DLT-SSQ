"""
PNG 热力图渲染器 - 用 matplotlib 生成静态图片
适合：推送时附带图、生成日报、保存到本地
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np

import matplotlib
matplotlib.use("Agg")  # 非 GUI 后端
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 中文字体设置
try:
    rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class ImageRenderer:
    """静态 PNG 图片渲染器（推送用）"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render_heatmap_png(
        self,
        front_scores: np.ndarray,
        back_scores: np.ndarray,
        period: str = "",
        filename: str = None,
    ) -> Path:
        """
        生成综合热度 PNG（深色背景，适合推送）

        Args:
            front_scores: shape (35,) 前区综合热度
            back_scores:  shape (12,) 后区综合热度
            period: 期号标签（可选）
            filename: 文件名（可选）

        Returns: PNG 文件路径
        """
        if filename is None:
            filename = f"heatmap_{period or 'latest'}.png"
        out_path = self.output_dir / filename

        # 创建画布
        fig, axes = plt.subplots(2, 1, figsize=(14, 6), facecolor="#0f172a")
        fig.suptitle(
            f"大乐透号码热度 · 第 {period} 期" if period else "大乐透号码热度",
            color="#fbbf24", fontsize=16, fontweight="bold", y=0.98,
        )

        # ---------- 前区 ----------
        ax1 = axes[0]
        self._draw_bar_heatmap(ax1, list(range(1, 36)), front_scores, "前区 1-35")

        # ---------- 后区 ----------
        ax2 = axes[1]
        self._draw_bar_heatmap(ax2, list(range(1, 13)), back_scores, "后区 1-12")

        plt.tight_layout()
        plt.savefig(out_path, dpi=120, facecolor="#0f172a", bbox_inches="tight")
        plt.close(fig)
        return out_path

    def render_ranking_png(
        self,
        scores: np.ndarray,
        numbers: List[int],
        zone_name: str = "前区",
        top_k: int = 15,
        period: str = "",
        filename: str = None,
    ) -> Path:
        """生成号码排行榜 PNG"""
        if filename is None:
            filename = f"ranking_{period or 'latest'}.png"
        out_path = self.output_dir / filename

        idx = np.argsort(scores)[::-1][:top_k]
        sorted_numbers = [numbers[i] for i in idx]
        sorted_scores = scores[idx]

        colors = []
        for s in sorted_scores:
            if s >= 0.75:
                colors.append("#dc2626")
            elif s >= 0.45:
                colors.append("#fbbf24")
            else:
                colors.append("#1e3a8a")

        fig, ax = plt.subplots(figsize=(8, 6), facecolor="#0f172a")
        ax.set_facecolor("#1e293b")

        bars = ax.barh(
            range(len(sorted_numbers)),
            sorted_scores,
            color=colors,
            edgecolor="white",
            linewidth=0.5,
        )
        ax.set_yticks(range(len(sorted_numbers)))
        ax.set_yticklabels([f"号码 {n:02d}" for n in sorted_numbers], color="white", fontsize=11)
        ax.invert_yaxis()
        ax.set_xlabel("热度评分", color="white", fontsize=11)
        ax.set_title(
            f"{zone_name}热度 Top {top_k} · 第 {period} 期" if period else f"{zone_name}热度 Top {top_k}",
            color="#fbbf24", fontsize=14, fontweight="bold", pad=10,
        )

        # 在柱子上标数字
        for i, (bar, s) in enumerate(zip(bars, sorted_scores)):
            ax.text(s + 0.01, i, f"{s:.3f}", va="center", color="white", fontsize=9)

        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.grid(True, axis="x", alpha=0.2, color="#94a3b8")
        ax.set_xlim(0, 1.05)

        plt.tight_layout()
        plt.savefig(out_path, dpi=120, facecolor="#0f172a", bbox_inches="tight")
        plt.close(fig)
        return out_path

    def render_combined_png(
        self,
        front_scores: np.ndarray,
        back_scores: np.ndarray,
        hit_report: Optional[Dict] = None,
        period: str = "",
        filename: str = None,
    ) -> Path:
        """
        生成综合报告 PNG（含命中评估，适合推送钉钉/企微）
        """
        if filename is None:
            filename = f"report_{period or 'latest'}.png"
        out_path = self.output_dir / filename

        fig = plt.figure(figsize=(14, 8), facecolor="#0f172a")
        gs = fig.add_gridspec(3, 2, hspace=0.4, wspace=0.3)

        # 前区热度
        ax1 = fig.add_subplot(gs[0, :])
        self._draw_bar_heatmap(ax1, list(range(1, 36)), front_scores, "前区 1-35")

        # 后区热度
        ax2 = fig.add_subplot(gs[1, :])
        self._draw_bar_heatmap(ax2, list(range(1, 13)), back_scores, "后区 1-12")

        # 命中评估
        if hit_report:
            ax3 = fig.add_subplot(gs[2, :])
            self._draw_hit_summary(ax3, hit_report)
            title = f"大乐透热度报告 · 第 {period} 期 · {hit_report.get('summary', '')}"
        else:
            title = f"大乐透热度报告 · 第 {period} 期"

        fig.suptitle(title, color="#fbbf24", fontsize=16, fontweight="bold", y=0.995)

        plt.savefig(out_path, dpi=120, facecolor="#0f172a", bbox_inches="tight")
        plt.close(fig)
        return out_path

    # ----------------------------------------------------------
    # 内部绘图
    # ----------------------------------------------------------

    def _draw_bar_heatmap(self, ax, numbers: List[int], scores: np.ndarray, title: str):
        """绘制横向条形热度图"""
        ax.set_facecolor("#1e293b")

        colors = []
        for s in scores:
            if s >= 0.75:
                colors.append("#dc2626")
            elif s >= 0.45:
                colors.append("#fbbf24")
            else:
                colors.append("#1e3a8a")

        bars = ax.bar(
            [str(n) for n in numbers],
            scores,
            color=colors,
            edgecolor="white",
            linewidth=0.3,
        )
        ax.set_title(title, color="#fbbf24", fontsize=12, fontweight="bold", pad=8)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("热度", color="white", fontsize=10)
        ax.tick_params(colors="white", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.grid(True, axis="y", alpha=0.2, color="#94a3b8")

    def _draw_hit_summary(self, ax, hit_report: Dict):
        """绘制命中评估摘要"""
        ax.set_facecolor("#1e293b")
        ax.axis("off")

        summary = hit_report.get("summary", "")
        ax.text(
            0.5, 0.7, summary, ha="center", va="center",
            color="#fbbf24", fontsize=20, fontweight="bold",
            transform=ax.transAxes,
        )

        front_hits = hit_report.get("front_hit_count", 0)
        back_hits = hit_report.get("back_hit_count", 0)
        ax.text(
            0.5, 0.3,
            f"前区命中 {front_hits}/5   ·   后区命中 {back_hits}/{hit_report.get('back_top_k', 6)}",
            ha="center", va="center",
            color="white", fontsize=14,
            transform=ax.transAxes,
        )


# ============================================================
# CLI 测试
# ============================================================
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import numpy as np
    rng = np.random.default_rng(42)
    front_scores = rng.random(35)
    back_scores = rng.random(12)

    renderer = ImageRenderer()
    p1 = renderer.render_heatmap_png(front_scores, back_scores, period="TEST")
    print(f"heatmap PNG: {p1}")

    p2 = renderer.render_ranking_png(front_scores, list(range(1, 36)), "前区", top_k=15, period="TEST")
    print(f"ranking PNG: {p2}")
