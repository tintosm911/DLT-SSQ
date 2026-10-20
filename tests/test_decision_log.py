"""测试决策日志"""
import pytest
import tempfile
from pathlib import Path
import pandas as pd

from analytics.decision_log import DecisionLog


@pytest.fixture
def tmp_log(tmp_path):
    """临时日志路径"""
    return tmp_path / "test_decision_log.csv"


class TestDecisionLog:
    def test_init_creates_file(self, tmp_log):
        log = DecisionLog(log_path=tmp_log)
        assert tmp_log.exists()

    def test_log_recommendation(self, tmp_log, sample_df):
        log = DecisionLog(log_path=tmp_log)
        tickets = [
            {"strategy": "TopHeat", "index": 1, "front": "01 02 03 04 05", "back": "03 09"},
            {"strategy": "TopHeat", "index": 2, "front": "06 07 08 09 10", "back": "01 12"},
        ]
        count = log.log_recommendation("2024001", tickets)
        assert count == 2

        df = pd.read_csv(tmp_log)
        assert len(df) == 2
        # period 在 CSV 里被读为字符串或数字都可能，强制转 str 比较
        assert str(df.iloc[0]["period"]) == "2024001"

    def test_prize_classification(self):
        """测试奖级分类"""
        assert DecisionLog._classify_prize(5, 2) == "一等奖"
        assert DecisionLog._classify_prize(5, 1) == "二等奖"
        assert DecisionLog._classify_prize(5, 0) == "三等奖"
        assert DecisionLog._classify_prize(4, 2) == "四等奖"
        assert DecisionLog._classify_prize(4, 1) == "五等奖"
        assert DecisionLog._classify_prize(4, 0) == "六等奖"
        assert DecisionLog._classify_prize(3, 2) == "七等奖"
        assert DecisionLog._classify_prize(3, 1) == "八等奖"
        assert DecisionLog._classify_prize(2, 2) == "八等奖"
        assert DecisionLog._classify_prize(3, 0) == "九等奖"
        assert DecisionLog._classify_prize(0, 2) == "九等奖"
        assert DecisionLog._classify_prize(0, 0) == "未中奖"
        assert DecisionLog._classify_prize(1, 0) == "未中奖"

    def test_backfill_results(self, tmp_log, sample_df, monkeypatch):
        """测试回填功能（用 sample_df 作为数据源）"""
        # monkeypatch data.load_lottery_data（decision_log 内部从 data 模块导入）
        import data
        monkeypatch.setattr(data, "load_lottery_data", lambda: sample_df)

        log = DecisionLog(log_path=tmp_log)
        tickets = [
            {"strategy": "TopHeat", "index": 1, "front": "01 02 03 04 05", "back": "03 09"},
        ]
        log.log_recommendation("TEST0000", tickets)

        # 回填
        filled = log.backfill_results(period="TEST0000")
        assert filled == 1

        df = pd.read_csv(tmp_log)
        assert str(df.iloc[0]["actual_front"]) != ""
        assert str(df.iloc[0]["actual_back"]) != ""
        assert int(df.iloc[0]["front_hits"]) >= 0
        assert int(df.iloc[0]["back_hits"]) >= 0

    def test_get_stats(self, tmp_log, sample_df, monkeypatch):
        """测试统计功能"""
        import data
        monkeypatch.setattr(data, "load_lottery_data", lambda: sample_df)

        log = DecisionLog(log_path=tmp_log)
        tickets = [
            {"strategy": "TopHeat", "index": 1, "front": "01 02 03 04 05", "back": "03 09"},
        ]
        log.log_recommendation("TEST0000", tickets)
        log.backfill_results()

        stats = log.get_stats(last_n_periods=10)
        assert "total_logged" in stats
        assert stats["total_logged"] == 1
        assert stats["filled"] == 1

    def test_get_stats_empty(self, tmp_log):
        log = DecisionLog(log_path=tmp_log)
        stats = log.get_stats()
        assert stats["total_logged"] == 0
        assert "message" in stats
