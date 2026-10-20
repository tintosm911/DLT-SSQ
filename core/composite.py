"""
综合热度评分 - 把多个算法按权重融合
输出一份 [0, 1] 的最终热度分数，用于"今天哪些号热"
"""
from __future__ import annotations
from typing import Dict, Any, List
import numpy as np

from .base import HeatAlgorithm
from .frequency import FrequencyAlgorithm
from .missing import MissingAlgorithm
from .weighted_window import WeightedWindowAlgorithm
from .ewma import EWMAAlgorithm
from .bayesian import BayesianAlgorithm
from .zscore import ZScoreAlgorithm


class CompositeAlgorithm(HeatAlgorithm):
    """
    综合热度评分
    final_score = Σ(wᵢ × normalized(scoreᵢ))
    所有子算法的分数先归一化到 [0, 1]，再按 config 中的权重加权求和
    """
    name = "composite"
    description = "综合热度评分（多算法加权融合）"
    requires_config = ["composite_weights"]

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.weights = self.config.get("composite_weights", {})

        # 默认权重
        default_weights = {
            "frequency": 0.10,
            "missing_inverse": 0.15,
            "weighted_window": 0.20,
            "ewma": 0.20,
            "bayesian": 0.15,
            "zscore": 0.20,
        }
        for k, v in default_weights.items():
            self.weights.setdefault(k, v)

        # 实例化所有子算法
        self.sub_algorithms = {
            "frequency": FrequencyAlgorithm(config),
            "missing_inverse": MissingAlgorithm(config),
            "weighted_window": WeightedWindowAlgorithm(config),
            "ewma": EWMAAlgorithm(config),
            "bayesian": BayesianAlgorithm(config),
            "zscore": ZScoreAlgorithm(config),
        }

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        if len(onehot) == 0:
            return np.zeros(n_range)

        # 1. 跑所有子算法
        scores_dict: Dict[str, np.ndarray] = {}
        for name, algo in self.sub_algorithms.items():
            try:
                scores_dict[name] = algo.compute(onehot, n_range)
            except Exception as e:
                # 单个算法失败不影响综合评分
                scores_dict[name] = np.zeros(n_range)

        # 2. 加权融合
        final = np.zeros(n_range, dtype=float)
        total_weight = sum(self.weights.values())

        if total_weight <= 0:
            # 权重全 0 时等权平均
            weights_norm = {k: 1.0 / len(scores_dict) for k in scores_dict}
        else:
            weights_norm = {k: v / total_weight for k, v in self.weights.items()}

        for name, scores in scores_dict.items():
            w = weights_norm.get(name, 0.0)
            final += w * scores

        return final

    def get_sub_scores(self, onehot: np.ndarray, n_range: int) -> Dict[str, np.ndarray]:
        """返回所有子算法的分数（用于详细分析）"""
        result = {}
        for name, algo in self.sub_algorithms.items():
            try:
                result[name] = algo.compute(onehot, n_range)
            except Exception:
                result[name] = np.zeros(n_range)
        result["composite"] = self.compute(onehot, n_range)
        return result


# 便捷函数
def compute_all_heat_scores(onehot: np.ndarray, n_range: int, config: Dict[str, Any] = None) -> Dict[str, np.ndarray]:
    """一次性算出所有算法的分数"""
    composite = CompositeAlgorithm(config)
    return composite.get_sub_scores(onehot, n_range)


def classify_hot_cold(scores: np.ndarray, thresholds: Dict[str, float] = None) -> Dict[str, list]:
    """
    根据综合评分把号码分成热/温/冷
    返回: {"hot": [号码列表], "warm": [...], "cold": [...]}
    """
    thresholds = thresholds or {"hot": 0.75, "warm": 0.45}
    hot_th = thresholds.get("hot", 0.75)
    warm_th = thresholds.get("warm", 0.45)

    hot = [i + 1 for i, s in enumerate(scores) if s >= hot_th]
    warm = [i + 1 for i, s in enumerate(scores) if warm_th <= s < hot_th]
    cold = [i + 1 for i, s in enumerate(scores) if s < warm_th]

    return {"hot": hot, "warm": warm, "cold": cold}
