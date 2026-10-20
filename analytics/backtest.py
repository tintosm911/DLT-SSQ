"""
回测引擎 - 验证算法在历史数据上的表现
"""
from __future__ import annotations
from typing import List, Optional, Callable

import numpy as np
import pandas as pd

from core import compute_all_heat_scores


class Backtester:
    """滑动窗口回测引擎"""

    def __init__(self, df: pd.DataFrame, zone: str = "front", top_k: int = 12):
        self.df = df.reset_index(drop=True)
        self.zone = zone
        self.top_k = top_k
        self.ball_per_period = 5 if zone == "front" else 2
        self.n_range = 35 if zone == "front" else 12
        self.onehot = self._build_onehot()

    def _build_onehot(self) -> np.ndarray:
        cols = [c for c in self.df.columns if c.startswith(f"{self.zone}_")]
        matrix = np.zeros((len(self.df), self.n_range), dtype=np.int8)
        for col in cols:
            nums = self.df[col].values - 1
            np.put_along_axis(matrix, nums[:, None], 1, axis=1)
        return matrix

    def run(
        self,
        algorithm: str = "composite",
        train_window: int = 200,
        test_periods: int = 500,
    ) -> dict:
        """
        跑滑动窗口回测

        Args:
            algorithm: 算法名 (frequency/missing/ewma/...)
            train_window: 训练窗口大小
            test_periods: 测试期数
        """
        n_total = len(self.onehot)
        test_start = n_total - test_periods

        hits_per_period = []

        for t in range(test_start, n_total):
            train_data = self.onehot[t - train_window:t]
            actual = self.onehot[t]
            actual_set = set((np.where(actual == 1)[0] + 1).tolist())

            scores = compute_all_heat_scores(train_data, self.n_range)
            if algorithm in scores:
                scores = scores[algorithm]
            else:
                scores = scores["composite"]

            # 取分数最高的 top_k 个号码
            top_idx = np.argsort(scores)[::-1][:self.top_k]
            pick_set = set((top_idx + 1).tolist())

            hit_count = len(pick_set & actual_set)
            hits_per_period.append(hit_count / self.ball_per_period)

        hits_arr = np.array(hits_per_period)
        return {
            "algorithm": algorithm,
            "n_periods": len(hits_arr),
            "avg_hit_rate": float(hits_arr.mean()),
            "std_hit_rate": float(hits_arr.std(ddof=1)),
            "theoretical_random": self.top_k / self.n_range,
            "hit_rates": hits_arr,
        }