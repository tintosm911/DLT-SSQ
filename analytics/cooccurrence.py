"""
号码共现分析
=============
统计两个号码同时出现的频率, 识别"关联组合"
"""
from __future__ import annotations
from typing import List, Tuple, Dict

import numpy as np
import pandas as pd


class CooccurrenceAnalyzer:
    """号码共现分析器"""

    def __init__(self, df: pd.DataFrame, zone: str = "front"):
        self.zone = zone
        self.cols = [c for c in df.columns if c.startswith(f"{zone}_")]
        self.n_range = 35 if zone == "front" else 12
        self.onehot = self._build_onehot(df)

    def _build_onehot(self, df: pd.DataFrame) -> np.ndarray:
        matrix = np.zeros((len(df), self.n_range), dtype=np.int8)
        for col in self.cols:
            nums = df[col].values - 1
            np.put_along_axis(matrix, nums[:, None], 1, axis=1)
        return matrix

    def cooccurrence_matrix(self) -> np.ndarray:
        """计算共现矩阵 M[i,j] = i 和 j 同时出现的期数"""
        return self.onehot.T @ self.onehot

    def top_pairs(self, top_k: int = 20) -> List[Tuple[int, int, int]]:
        """Top K 共现号码对 (0-indexed)"""
        matrix = self.cooccurrence_matrix()
        pairs = []
        for i in range(self.n_range):
            for j in range(i + 1, self.n_range):
                if matrix[i, j] > 0:
                    pairs.append((i + 1, j + 1, int(matrix[i, j])))
        pairs.sort(key=lambda x: -x[2])
        return pairs[:top_k]

    def conditional_prob(self, num1: int, num2: int) -> float:
        """
        P(num2 | num1) - 给定 num1 出现, num2 出现的条件概率
        num1, num2: 1-indexed
        """
        idx1, idx2 = num1 - 1, num2 - 1
        n1 = self.onehot[:, idx1].sum()
        if n1 == 0:
            return 0.0
        n12 = (self.onehot[:, idx1] & self.onehot[:, idx2]).sum()
        return n12 / n1

    def summary(self) -> Dict:
        """汇总统计"""
        matrix = self.cooccurrence_matrix()
        diag = np.diag(matrix)
        n_periods = len(self.onehot)
        return {
            "n_periods": n_periods,
            "n_range": self.n_range,
            "avg_alone_freq": float(diag.mean() / n_periods),
            "max_pair_count": int(matrix[~np.eye(self.n_range, dtype=bool)].max()),
            "top_pairs": self.top_pairs(10),
        }