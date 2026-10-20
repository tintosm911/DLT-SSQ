"""
AnySportSource 测试
"""
import os
import pytest
from unittest.mock import patch, AsyncMock

from sports.data_sources import AnySportSource, MockSource, DataSourceRouter


class TestAnySportSource:
    """AnySportSource 单元测试"""

    def test_init_without_api_key(self):
        """未配置 key 时应该警告但不崩溃"""
        os.environ.pop("ANYSPORT_API_KEY", None)
        src = AnySportSource()
        assert src._available is False
        assert src.api_key == ""

    def test_init_with_api_key_arg(self):
        """通过参数传入 key"""
        src = AnySportSource(api_key="test_key_xxx")
        assert src._available is True
        assert src.api_key == "test_key_xxx"

    def test_init_with_env_var(self):
        """通过环境变量读 key"""
        with patch.dict(os.environ, {"ANYSPORT_API_KEY": "env_key_xxx"}):
            src = AnySportSource()
            assert src._available is True
            assert src.api_key == "env_key_xxx"

    def test_fetch_matches_without_key_raises(self):
        """未配置 key 时 fetch_matches 应该抛错"""
        os.environ.pop("ANYSPORT_API_KEY", None)
        src = AnySportSource()
        with pytest.raises(RuntimeError, match="AnySport API key 未配置"):
            src.fetch_matches("epl", "2024-2025")

    def test_fetch_odds_without_key_raises(self):
        os.environ.pop("ANYSPORT_API_KEY", None)
        src = AnySportSource()
        with pytest.raises(RuntimeError, match="AnySport API key 未配置"):
            src.fetch_odds(["m1", "m2"])

    def test_priority_highest(self):
        """AnySport 优先级应该最高 (5 < 10 < 999)"""
        assert AnySportSource.priority < MockSource.priority

    def test_rate_limit_tracking(self):
        """限流计数应该正确"""
        src = AnySportSource(api_key="test_key")
        src._calls_this_hour = 119  # 差一次到上限
        src._check_rate_limit()  # 应该 OK
        with pytest.raises(RuntimeError, match="已用满"):
            src._check_rate_limit()  # 应该抛错

    def test_parse_match_success(self):
        """解析 match JSON 成功"""
        src = AnySportSource(api_key="test_key")
        item = {
            "match_id": "as_abc123",
            "league_id": "asl_xyz",
            "season": "2024",
            "home": {"name": "Team A"},
            "away": {"name": "Team B"},
            "home_score": 2,
            "away_score": 1,
            "status": "Finished",
            "time_utc": "2024-09-01T15:00:00Z",
        }
        match = src._parse_match(item)
        assert match is not None
        assert match.home_team == "Team A"
        assert match.away_team == "Team B"
        assert match.home_score == 2
        assert match.away_score == 1
        assert match.is_finished

    def test_parse_match_unfinished(self):
        """未完赛时 outcome 应为 None"""
        src = AnySportSource(api_key="test_key")
        item = {
            "match_id": "as_xyz",
            "league_id": "asl_xyz",
            "home": {"name": "A"},
            "away": {"name": "B"},
            "home_score": None,
            "away_score": None,
            "status": "Not Started",
            "time_utc": "2024-09-01T15:00:00Z",
        }
        match = src._parse_match(item)
        assert match is not None
        assert match.outcome is None
        assert match.is_finished is False

    def test_parse_prematch_odds_success(self):
        """解析 prematch odds JSON 成功"""
        src = AnySportSource(api_key="test_key")
        item = {
            "match_id": "as_abc",
            "bookmaker": "bet365",
            "main_market": "match_winner",
            "home_odd": 1.5,
            "draw_odd": 4.0,
            "away_odd": 6.0,
            "updated_at": "2024-09-01T14:00:00Z",
        }
        odds = src._parse_prematch_odds(item)
        assert odds is not None
        assert odds.home_odds == 1.5
        assert odds.draw_odds == 4.0
        assert odds.away_odds == 6.0
        assert odds.bookmaker == "bet365"

    def test_parse_prematch_odds_skip_non_winner(self):
        """非胜平负市场应该跳过"""
        src = AnySportSource(api_key="test_key")
        item = {
            "match_id": "as_abc",
            "main_market": "asian_handicap",
            "home_odd": 1.5,
            "draw_odd": 4.0,
            "away_odd": 6.0,
            "updated_at": "2024-09-01T14:00:00Z",
        }
        odds = src._parse_prematch_odds(item)
        assert odds is None


class TestDataSourceRouter:
    """数据源路由器测试"""

    def test_router_with_anysport_and_mock(self):
        """Router 应该同时注册 AnySport 和 Mock"""
        router = DataSourceRouter()
        sources = router.list_sources()
        assert "anysport" in sources
        assert "mock" in sources

    def test_router_anysport_first(self):
        """AnySport 应该在 Mock 之前 (优先级高)"""
        router = DataSourceRouter()
        sources = router.list_sources()
        assert sources.index("anysport") < sources.index("mock")

    def test_router_falls_back_when_no_key(self):
        """AnySport 无 key 时自动降级到 Mock"""
        os.environ.pop("ANYSPORT_API_KEY", None)
        router = DataSourceRouter()
        matches = router.fetch_matches("epl", "2024-2025")
        assert len(matches) > 0  # 来自 Mock

    def test_router_with_explicit_key(self):
        """显式传 key 时 AnySport 优先 (但 fetch 仍会因 league_id 未填失败 → fallback)"""
        router = DataSourceRouter(anysport_api_key="dummy_key")
        matches = router.fetch_matches("epl", "2024-2025")
        assert len(matches) > 0  # fallback 到 mock