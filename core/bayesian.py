"""
贝叶斯热度估计 - Beta-Binomial 共轭
"""
from __future__ import annotations
import numpy as np
from .base import HeatAlgorithm


class BayesianAlgorithm(HeatAlgorithm):
    """贝叶斯热度估计 (Beta-Binomial 共轭)"""

    name = "bayesian"

    def __init__(self, prior_alpha: float = 1.0, prior_beta: float = None):
        """
        Args:
            prior_alpha: 先验 α (成功次数伪计数)
            prior_beta: 先验 β (失败次数伪计数, 默认 = n_range - front_count)
        """
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta

    def compute(self, onehot: np.ndarray, n_range: int) -> np.ndarray:
        """返回贝叶斯后验均值"""
        prior_beta = self.prior_beta if self.prior_beta is not None else float(n_range - 5)
        n_periods = len(onehot)

        # 每个号码的命中次数
        hits = onehot.sum(axis=0).astype(float)
        misses = n_periods - hits

        # 后验均值 = (α + k) / (α + β + n)
        alpha_post = self.prior_alpha + hits
        beta_post = prior_beta + misses
        return alpha_post / (alpha_post + beta_post)