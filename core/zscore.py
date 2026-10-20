"""
Z-Score 偏离度 - 偏离期望频率的程度
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class ZScoreAlgorithm(HeatAlgorithm):
    """Z-Score 偏离度"""

    name = "zscore"

    def __init__(self, expected_per_period: float = None):
        self.expected_per_period = expected_per_period

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """返回每个号码的 Z-Score"""
        n_periods = len(onehot)
        # 期望频率 = n_periods * (front_count / n_range)
        if self.expected_per_period is None:
            expected_per_period = n_periods * (5.0 / n_range)
        else:
            expected_per_period = self.expected_per_period

        observed = onehot.sum(axis=0).astype(float)
        std = np.sqrt(expected_per_period * (1 - 5.0 / n_range))
        return (observed - expected_per_period) / std if std > 0 else np.zeros(n_range)