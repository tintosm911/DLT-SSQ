"""
热度对比器 - 拿新开奖后立即评估"如果按热度选号能中多少"
主要场景：开奖后立刻看自己选号策略的命中效果
"""
from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data_fetcher import Draw
from core import compute_all_heat_scores, classify_hot_cold

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data-raw"


@dataclass
class HitReport:
    """单期命中报告"""
    period: str
    draw_date: str
    actual_front: List[int]
    actual_back: List[int]
    # 前区对比
    front_pick: List[int]              # 按热度选出的号码
    front_hits: List[int]              # 命中的号码
    front_hit_count: int
    front_top_k: int
    # 后区对比
    back_pick: List[int]
    back_hits: List[int]
    back_hit_count: int
    back_top_k: int
    # 状态
    front_actual_hot_warm_cold: Dict[str, int]  # 实际开奖号码的热度分布
    summary: str                       # 一句话总结


class HeatComparator:
    """
    热度对比器
    拿新开奖后，对比"按热度选 Top-K 号码" vs "实际开奖号码"的命中情况
    """

    def __init__(self, csv_path: Path = None):
        self.csv_path = csv_path or (DATA_DIR / "lottery_history.csv")

    def evaluate_new_draw(
        self,
        draw: Draw,
        front_top_k: int = 12,
        back_top_k: int = 6,
        window: int = 100,
    ) -> HitReport:
        """
        评估新开奖

        Args:
            draw: 拿到的最新一期
            front_top_k: 前区选前 K 个热号
            back_top_k: 后区选前 K 个热号
            window: 计算热度用的最近 N 期历史

        Returns:
            HitReport
        """
        # 1. 加载历史
        df = self._load_history()
        if df is None or len(df) < 10:
            logger.warning("历史数据不足，无法评估")
            return self._empty_report(draw)

        # 2. 用最近 window 期算热度（不含 draw 本身）
        recent_df = df.tail(window).reset_index(drop=True)

        # 3. 前区热度
        front_cols = [c for c in recent_df.columns if c.startswith("front_")]
        front_onehot = self._build_onehot(recent_df, front_cols, 35)
        front_scores = compute_all_heat_scores(front_onehot, 35)
        front_composite = front_scores["composite"]

        # 前区 Top-K
        front_top_idx = np.argsort(front_composite)[::-1][:front_top_k]
        front_pick = sorted([int(i + 1) for i in front_top_idx])

        # 命中
        front_hits = sorted(list(set(front_pick) & set(draw.front)))

        # 4. 后区热度
        back_cols = [c for c in recent_df.columns if c.startswith("back_")]
        back_onehot = self._build_onehot(recent_df, back_cols, 12)
        back_scores = compute_all_heat_scores(back_onehot, 12)
        back_composite = back_scores["composite"]

        back_top_idx = np.argsort(back_composite)[::-1][:back_top_k]
        back_pick = sorted([int(i + 1) for i in back_top_idx])

        back_hits = sorted(list(set(back_pick) & set(draw.back)))

        # 5. 实际开奖号码的热度分类
        classification = classify_hot_cold(front_composite)
        front_distribution = {
            "hot": sum(1 for n in draw.front if n in classification["hot"]),
            "warm": sum(1 for n in draw.front if n in classification["warm"]),
            "cold": sum(1 for n in draw.front if n in classification["cold"]),
        }

        # 6. 总结
        if len(front_hits) >= 3:
            summary = f"🎉 前区命中 {len(front_hits)}/5！"
        elif len(front_hits) >= 2:
            summary = f"👍 前区命中 {len(front_hits)}/5"
        elif len(front_hits) >= 1:
            summary = f"前区命中 {len(front_hits)}/5"
        else:
            summary = "前区 0 中"

        if len(back_hits) == back_top_k:
            summary += f" · 后区全中({len(back_hits)}/{back_top_k}) 🎯"
        elif len(back_hits) > 0:
            summary += f" · 后区中 {len(back_hits)}/{back_top_k}"

        return HitReport(
            period=draw.period,
            draw_date=draw.draw_date,
            actual_front=draw.front,
            actual_back=draw.back,
            front_pick=front_pick,
            front_hits=front_hits,
            front_hit_count=len(front_hits),
            front_top_k=front_top_k,
            back_pick=back_pick,
            back_hits=back_hits,
            back_hit_count=len(back_hits),
            back_top_k=back_top_k,
            front_actual_hot_warm_cold=front_distribution,
            summary=summary,
        )

    def format_report(self, report: HitReport) -> Dict[str, str]:
        """格式化推送消息"""
        front_pick_str = " ".join(f"{n:02d}" for n in report.front_pick)
        front_hit_str = " ".join(f"{n:02d}" for n in report.front_hits) if report.front_hits else "（无）"
        back_pick_str = " ".join(f"{n:02d}" for n in report.back_pick)
        back_hit_str = " ".join(f"{n:02d}" for n in report.back_hits) if report.back_hits else "（无）"
        actual_front_str = " ".join(f"{n:02d}" for n in report.actual_front)
        actual_back_str = " ".join(f"{n:02d}" for n in report.actual_back)

        # 命中用红字突出
        front_pick_marked = " ".join(
            f"**{n:02d}**" if n in report.front_hits else f"{n:02d}"
            for n in report.front_pick
        )
        back_pick_marked = " ".join(
            f"**{n:02d}**" if n in report.back_hits else f"{n:02d}"
            for n in report.back_pick
        )

        return {
            "title": f"📊 第 {report.period} 期命中评估 · {report.summary}",
            "period": report.period,
            "draw_date": report.draw_date,
            "front_section": (
                f"**前区** (Top-{report.front_top_k} 命中 {report.front_hit_count}/5):\n"
                f"  选号: {front_pick_marked}\n"
                f"  实际: {actual_front_str}\n"
                f"  命中: {front_hit_str}"
            ),
            "back_section": (
                f"**后区** (Top-{report.back_top_k} 命中 {report.back_hit_count}/{report.back_top_k}):\n"
                f"  选号: {back_pick_marked}\n"
                f"  实际: {actual_back_str}\n"
                f"  命中: {back_hit_str}"
            ),
            "distribution": (
                f"  实际开奖: 热号 {report.front_actual_hot_warm_cold['hot']} · "
                f"温号 {report.front_actual_hot_warm_cold['warm']} · "
                f"冷号 {report.front_actual_hot_warm_cold['cold']}"
            ),
            "summary": report.summary,
        }

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _load_history(self) -> Optional[pd.DataFrame]:
        if not self.csv_path.exists():
            return None
        try:
            df = pd.read_csv(self.csv_path)
            # 归一化
            if "front" in df.columns:
                front_split = df["front"].str.split(",", expand=True).astype(int)
                front_split.columns = [f"front_{i+1}" for i in range(front_split.shape[1])]
                df = pd.concat([df.drop(columns=["front"]), front_split], axis=1)
            if "back" in df.columns:
                back_split = df["back"].str.split(",", expand=True).astype(int)
                back_split.columns = [f"back_{i+1}" for i in range(back_split.shape[1])]
                df = pd.concat([df.drop(columns=["back"]), back_split], axis=1)
            df["period"] = df["period"].astype(str)
            df = df.sort_values("period").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"加载历史失败: {e}")
            return None

    def _build_onehot(self, df: pd.DataFrame, cols: list, n_range: int) -> np.ndarray:
        matrix = np.zeros((len(df), n_range), dtype=np.int8)
        for col in cols:
            nums = df[col].values - 1
            np.put_along_axis(matrix, nums[:, None], 1, axis=1)
        return matrix

    def _empty_report(self, draw: Draw) -> HitReport:
        return HitReport(
            period=draw.period,
            draw_date=draw.draw_date,
            actual_front=draw.front,
            actual_back=draw.back,
            front_pick=[], front_hits=[], front_hit_count=0, front_top_k=0,
            back_pick=[], back_hits=[], back_hit_count=0, back_top_k=0,
            front_actual_hot_warm_cold={"hot": 0, "warm": 0, "cold": 0},
            summary="数据不足",
        )
