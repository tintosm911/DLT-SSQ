"""
指数加权移动平均 (EWMA) - 近期权重指数衰减
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class EWMAAlgorithm(HeatAlgorithm):
    """EWMA - 指数加权移动平均"""

    name = "ewma"

    def __init__(self, alpha: float = 0.3):
        """
        Args:
            alpha: 平滑系数 (0~1, 越大越看重近期)
        """
        self.alpha = alpha

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """返回每个号码的 EWMA 评分"""
        ewma = np.zeros(n_range)
        alpha = self.alpha
        for t in range(len(onehot)):
            ewma = alpha * onehot[t] + (1 - alpha) * ewma
        return ewma