"""
加权滑动窗口 - 近期数据权重更大
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class WeightedWindowAlgorithm(HeatAlgorithm):
    """加权滑动窗口 (线性递增权重, 越近期权重越大)"""

    name = "weighted_window"

    def __init__(self, window: int = 100):
        self.window = window

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """返回加权频率"""
        if self.window > 0 and self.window < len(onehot):
            data = onehot[-self.window:]
        else:
            data = onehot
        weights = np.linspace(0.5, 1.0, len(data))  # 越近期权重越大
        return (data * weights[:, None]).sum(axis=0)