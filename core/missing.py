"""
遗漏值分析 - 距离上次出现的期数
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class MissingAlgorithm(HeatAlgorithm):
    """计算每个号码当前遗漏期数 (距上次出现的期数)"""

    name = "missing"

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """
        返回每个号码的当前遗漏值
        (越大 = 越冷, 越小 = 越热)
        """
        n_periods = len(onehot)
        missing = np.zeros(n_range, dtype=int)
        for num in range(n_range):
            # 反向查找最后一个 1
            rev = onehot[::-1, num]
            idx = np.argmax(rev) if rev.any() else n_periods
            missing[num] = idx if rev.any() else n_periods
        return missing.astype(float)