"""
Recommender 测试 (覆盖 5 种推荐策略)
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import numpy as np
import pandas as pd

from analytics.recommender import Recommender


@pytest.fixture
def recommender(sample_df):
    """构造 Recommender 实例"""
    return Recommender(df=sample_df, game="dlt")


class TestRecommenderInit:
    """Recommender 初始化测试"""

    def test_init_with_df(self, sample_df):
        """用 DataFrame 初始化"""
        r = Recommender(df=sample_df, game="dlt")
        assert r.df is not None
        assert len(r.df) == len(sample_df)

    def test_init_default_game(self, sample_df):
        """默认彩种 = dlt"""
        r = Recommender(df=sample_df)
        assert r.game == "dlt"

    def test_init_ssq(self, sample_df):
        """双色球初始化"""
        r = Recommender(df=sample_df, game="ssq")
        assert r.game == "ssq"

    def test_init_unsupported_game_raises(self, sample_df):
        """未知彩种应该抛错"""
        with pytest.raises((ValueError, KeyError)):
            Recommender(df=sample_df, game="unknown_game")


class TestRecommenderStrategies:
    """5 种推荐策略测试"""

    def test_recommend_top_heat_returns_list(self, recommender):
        """Top Heat 推荐"""
        result = recommender.recommend_top_heat(n=5)
        assert isinstance(result, (list, tuple, pd.DataFrame))
        if hasattr(result, '__len__'):
            assert len(result) > 0

    def test_recommend_most_frequent(self, recommender):
        """Most Frequent 推荐"""
        result = recommender.recommend_most_frequent(n=5)
        assert result is not None

    def test_recommend_cold_rebound(self, recommender):
        """追冷推荐"""
        result = recommender.recommend_cold_rebound(n=5)
        assert result is not None

    def test_recommend_balanced(self, recommender):
        """均衡推荐"""
        result = recommender.recommend_balanced(n=5)
        assert result is not None

    def test_recommend_mixed_portfolio(self, recommender):
        """混合组合推荐"""
        result = recommender.recommend_mixed_portfolio(n=5)
        assert result is not None

    def test_recommend_for_period(self, recommender, sample_df):
        """为某期推荐"""
        target_period = sample_df.iloc[-1]["period"]
        result = recommender.recommend_for_period(period=target_period, n=5)
        assert result is not None

    def test_print_recommendations(self, recommender, capsys):
        """打印推荐结果"""
        recommender.print_recommendations(n=3)
        captured = capsys.readouterr()
        # 应该有一些输出
        assert len(captured.out) > 0 or len(captured.err) > 0


class TestRecommenderSSQ:
    """双色球 Recommender 测试"""

    def test_ssq_recommender(self, sample_df):
        """双色球也能正常工作"""
        r = Recommender(df=sample_df, game="ssq")
        result = r.recommend_top_heat(n=6)
        assert result is not None


class TestRecommenderEdgeCases:
    """边界条件测试"""

    def test_small_data(self):
        """小数据集也能跑"""
        df = pd.DataFrame({
            "period": ["T1", "T2", "T3"],
            "draw_date": ["2024-01-01", "2024-01-03", "2024-01-05"],
            "front_1": [1, 5, 10], "front_2": [2, 6, 11],
            "front_3": [3, 7, 12], "front_4": [4, 8, 13],
            "front_5": [5, 9, 14],
            "back_1": [1, 3, 5], "back_2": [2, 4, 6],
        })
        r = Recommender(df=df, game="dlt")
        # 不应该崩溃
        result = r.recommend_top_heat(n=5)
        assert result is not None