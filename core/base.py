"""
算法基类 - HeatAlgorithm
=========================
所有热度算法的统一接口

类名 HeatAlgorithm 保持与 composite.py 一致
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import numpy as np


class HeatAlgorithm(ABC):
    """所有热度算法的基类"""

    name: str = "base"
    description: str = ""
    requires_config: list = field(default_factory=list)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """
        计算热度评分

        Args:
            onehot: (n_periods, n_range) 0/1 矩阵
            n_range: 号码范围

        Returns:
            np.ndarray: 每个号码的评分 (长度 n_range)
        """
        pass

    def __call__(self, *args, **kwargs) -> np.ndarray:
        return self.compute(*args, **kwargs)


# 别名兼容 (新代码可用 BaseAlgorithm)
BaseAlgorithm = HeatAlgorithm


def normalize_scores(scores: np.ndarray, method: str = "minmax") -> np.ndarray:
    """归一化到 [0, 1]"""
    if method == "minmax":
        s_min, s_max = scores.min(), scores.max()
        if s_max == s_min:
            return np.full_like(scores, 0.5)
        return (scores - s_min) / (s_max - s_min)
    elif method == "zscore":
        std = scores.std()
        if std == 0:
            return np.zeros_like(scores)
        return (scores - scores.mean()) / std
    elif method == "rank":
        from scipy.stats import rankdata
        return rankdata(scores) / len(scores)
    else:
        return scores


@dataclass
class AlgorithmResult:
    scores: np.ndarray
    metadata: Dict = field(default_factory=dict)