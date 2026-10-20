"""
频率统计 - 最基础的号码热度
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class FrequencyAlgorithm(HeatAlgorithm):
    """简单频率统计"""

    name = "frequency"

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """返回每个号码的总出现次数"""
        return onehot.sum(axis=0).astype(float)