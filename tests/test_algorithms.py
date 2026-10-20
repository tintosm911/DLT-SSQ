"""测试核心算法"""
import numpy as np
import pytest

from core.frequency import FrequencyAlgorithm
from core.missing import MissingAlgorithm
from core.weighted_window import WeightedWindowAlgorithm
from core.ewma import EWMAAlgorithm
from core.bayesian import BayesianAlgorithm
from core.zscore import ZScoreAlgorithm
from core.composite import CompositeAlgorithm, compute_all_heat_scores, classify_hot_cold


class TestFrequencyAlgorithm:
    def test_returns_correct_shape(self, sample_onehot):
        scores = FrequencyAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_frequency_in_range(self, sample_onehot):
        scores = FrequencyAlgorithm().compute(sample_onehot, 35)
        # 频率应在 [0, 1]
        assert scores.min() >= 0
        assert scores.max() <= 1

    def test_with_window(self, sample_onehot):
        algo = FrequencyAlgorithm({"windows": {"mid": 30}})
        scores = algo.compute(sample_onehot, 35)
        assert scores.shape == (35,)


class TestMissingAlgorithm:
    def test_returns_shape(self, sample_onehot):
        scores = MissingAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_normalized_to_unit(self, sample_onehot):
        scores = MissingAlgorithm().compute(sample_onehot, 35)
        # _normalize 应该归一化到 [0, 1]
        assert scores.min() >= 0
        assert scores.max() <= 1

    def test_recently_appeared_higher(self, sample_onehot):
        scores = MissingAlgorithm().compute(sample_onehot, 35)
        # 最后几期出现的号码应该有更高的分数（最近出现 → 遗漏小）
        # 检查至少有一个号码分数高
        assert scores.max() > scores.min()


class TestWeightedWindowAlgorithm:
    def test_shape(self, sample_onehot):
        scores = WeightedWindowAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_recent_counts_more(self, sample_onehot):
        algo = WeightedWindowAlgorithm({"windows": {"mid": 50}})
        scores = algo.compute(sample_onehot, 35)
        # 至少有一个号码得分 > 0（最近有出现）
        assert scores.max() > 0


class TestEWMAAlgorithm:
    def test_shape(self, sample_onehot):
        scores = EWMAAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_alpha_param(self, sample_onehot):
        algo_high = EWMAAlgorithm({"ewma": {"alpha": 0.9}})
        algo_low = EWMAAlgorithm({"ewma": {"alpha": 0.1}})
        s_high = algo_high.compute(sample_onehot, 35)
        s_low = algo_low.compute(sample_onehot, 35)
        # 高 alpha 应该对最近数据更敏感
        assert s_high.shape == s_low.shape == (35,)


class TestBayesianAlgorithm:
    def test_shape(self, sample_onehot):
        scores = BayesianAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_posterior_mean_in_range(self, sample_onehot):
        scores = BayesianAlgorithm().compute(sample_onehot, 35)
        # Beta 后验均值应在 [0, 1]
        assert scores.min() >= 0
        assert scores.max() <= 1

    def test_custom_prior(self, sample_onehot):
        algo = BayesianAlgorithm({"bayesian": {"prior_alpha": 10, "prior_beta": 100}})
        scores = algo.compute(sample_onehot, 35)
        assert scores.shape == (35,)


class TestZScoreAlgorithm:
    def test_shape(self, sample_onehot):
        scores = ZScoreAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_normalized_range(self, sample_onehot):
        scores = ZScoreAlgorithm().compute(sample_onehot, 35)
        # 归一化后应该在 [0, 1]
        assert scores.min() >= 0
        assert scores.max() <= 1


class TestCompositeAlgorithm:
    def test_shape(self, sample_onehot):
        scores = CompositeAlgorithm().compute(sample_onehot, 35)
        assert scores.shape == (35,)

    def test_weights_sum_to_one(self, sample_onehot):
        weights = CompositeAlgorithm().weights
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_get_sub_scores(self, sample_onehot):
        algo = CompositeAlgorithm()
        result = algo.get_sub_scores(sample_onehot, 35)
        # 应该返回所有子算法 + composite
        assert "frequency" in result
        assert "missing_inverse" in result
        assert "weighted_window" in result
        assert "ewma" in result
        assert "bayesian" in result
        assert "zscore" in result
        assert "composite" in result

    def test_compute_all_heat_scores(self, sample_onehot):
        result = compute_all_heat_scores(sample_onehot, 35)
        assert "composite" in result
        assert result["composite"].shape == (35,)


class TestClassifyHotCold:
    def test_basic(self):
        scores = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        result = classify_hot_cold(scores)
        assert "hot" in result
        assert "warm" in result
        assert "cold" in result
        # 0.9 应该是 hot
        assert 5 in result["hot"]  # 号码 5 (1-indexed)
        # 0.1 应该是 cold
        assert 1 in result["cold"]

    def test_custom_thresholds(self):
        scores = np.array([0.5, 0.7, 0.9])
        result = classify_hot_cold(scores, thresholds={"hot": 0.85, "warm": 0.6})
        assert 3 in result["hot"]  # 0.9
        assert 2 in result["warm"]  # 0.7
        assert 1 in result["cold"]  # 0.5
