"""
走势分析 - 寻找号码的热度拐点
如果某个号码连续上升 N 期，可能进入"热状态"
"""
from __future__ import annotations
from typing import List, Dict
import numpy as np
import pandas as pd


class TrendAnalyzer:
    """
    趋势分析器
    - 移动平均线（识别长期趋势）
    - 拐点检测（热度上升/下降的转折）
    - 动量指标（最近 N 期连续上升/下降的强度）
    """

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

    def get_rolling_window(self, number: int, window: int = 10) -> np.ndarray:
        """
        号码最近 N 期每一期是否出现的序列
        返回: shape (window,), [1, 0, 1, 1, ...]
        """
        idx = number - 1
        return self.onehot[-window:, idx]

    def get_rolling_frequency(self, number: int, window: int = 30) -> np.ndarray:
        """
        号码最近 N 期的滚动频率（每期为过去 window 期的平均）
        """
        idx = number - 1
        col = self.onehot[:, idx].astype(float)
        # 用累积和计算滚动平均
        cumsum = np.cumsum(col)
        result = np.zeros(len(col))
        for i in range(len(col)):
            start = max(0, i - window + 1)
            result[i] = cumsum[i] - (cumsum[start - 1] if start > 0 else 0)
            result[i] /= (i - start + 1)
        return result

    def get_momentum(self, number: int, lookback: int = 10) -> Dict:
        """
        动量：最近 lookback 期相对前 lookback 期的热度变化
        - 上升动量（最近更热）
        - 拐点位置（变化最强的点）
        """
        idx = number - 1
        col = self.onehot[:, idx].astype(float)

        if len(col) < 2 * lookback:
            return {"momentum": 0, "trend": "insufficient_data"}

        recent = col[-lookback:].sum()
        previous = col[-2 * lookback:-lookback].sum()
        momentum = recent - previous

        if momentum > 0:
            trend = "rising"
        elif momentum < 0:
            trend = "falling"
        else:
            trend = "stable"

        return {
            "number": number,
            "recent_count": int(recent),
            "previous_count": int(previous),
            "momentum": int(momentum),
            "trend": trend,
        }

    def detect_inflection(self, number: int, window: int = 30) -> Dict:
        """
        检测最近是否有热度拐点
        拐点 = 滚动频率变化率最大的位置
        """
        idx = number - 1
        col = self.onehot[:, idx].astype(float)

        if len(col) < window + 5:
            return {"inflection": False, "reason": "insufficient_data"}

        # 滚动频率
        rolling = self.get_rolling_frequency(number, window=5)

        # 计算一阶差分（变化率）
        diff = np.diff(rolling)

        # 最近 window 期内最大变化
        recent_diff = diff[-window:]
        max_change_idx = np.argmax(np.abs(recent_diff))
        max_change = recent_diff[max_change_idx]

        return {
            "number": number,
            "has_inflection": abs(max_change) > 0.05,
            "direction": "up" if max_change > 0 else "down",
            "magnitude": float(max_change),
            "position": len(col) - window + max_change_idx,
        }

    def get_status(self, number: int, recent_n: int = 10) -> str:
        """
        简单的号码状态判定
        - "hot_streak": 最近 N 期 ≥ 3 次出现
        - "cold_streak": 最近 N 期 0 次出现
        - "warming": 有出现但 ≤ 2 次
        - "stable": 其他
        """
        recent = self.get_rolling_window(number, recent_n)
        cnt = recent.sum()
        if cnt >= 3:
            return "hot_streak"
        elif cnt == 0:
            return "cold_streak"
        elif cnt > 0:
            return "warming"
        return "stable"
