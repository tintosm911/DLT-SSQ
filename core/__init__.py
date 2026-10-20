"""
core - 7 种核心热度算法包
==========================

算法列表:
  1. FrequencyAlgorithm     - 简单频率统计
  2. MissingAlgorithm       - 遗漏值分析
  3. WeightedWindowAlgorithm- 加权滑动窗口
  4. EWMAAlgorithm          - 指数加权移动平均
  5. BayesianAlgorithm      - 贝叶斯热度估计
  6. ZScoreAlgorithm        - Z-Score 偏离度
  7. CompositeAlgorithm     - 综合评分 (其他算法的加权平均)

主入口:
  compute_all_heat_scores(onehot, n_range) -> Dict[str, np.ndarray]
"""
from .frequency import FrequencyAlgorithm
from .missing import MissingAlgorithm
from .weighted_window import WeightedWindowAlgorithm
from .ewma import EWMAAlgorithm
from .bayesian import BayesianAlgorithm
from .zscore import ZScoreAlgorithm
from .composite import CompositeAlgorithm
from .base import HeatAlgorithm, BaseAlgorithm, AlgorithmResult

import numpy as np
from typing import Dict, List, Optional

__all__ = [
    "FrequencyAlgorithm",
    "MissingAlgorithm",
    "WeightedWindowAlgorithm",
    "EWMAAlgorithm",
    "BayesianAlgorithm",
    "ZScoreAlgorithm",
    "CompositeAlgorithm",
    "HeatAlgorithm",
    "BaseAlgorithm",
    "AlgorithmResult",
    "compute_all_heat_scores",
]


def compute_all_heat_scores(
    onehot: np.ndarray,
    n_range: int,
    window: int = 100,
) -> Dict[str, np.ndarray]:
    """
    计算所有 7 种算法的热度评分

    Args:
        onehot: (n_periods, n_range) 0/1 矩阵
        n_range: 号码范围 (大乐透前区 35, 后区 12)
        window: 滑动窗口大小

    Returns:
        Dict[str, np.ndarray]: 算法名 → 评分数组
    """
    algorithms = [
        ("frequency", FrequencyAlgorithm()),
        ("missing", MissingAlgorithm()),
        ("weighted_window", WeightedWindowAlgorithm(window=window)),
        ("ewma", EWMAAlgorithm(alpha=0.3)),
        ("bayesian", BayesianAlgorithm()),
        ("zscore", ZScoreAlgorithm()),
    ]

    scores = {}
    for name, algo in algorithms:
        try:
            scores[name] = algo.compute(onehot, n_range)
        except Exception as e:
            scores[name] = np.zeros(n_range)

    # 综合评分
    try:
        composite = CompositeAlgorithm(weights={name: 1.0 for name in scores})
        scores["composite"] = composite.compute_from_dict(scores)
    except Exception:
        scores["composite"] = np.mean(list(scores.values()), axis=0)

    return scores