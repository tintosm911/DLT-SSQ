"""测试多数据源路由器"""
import pytest
from unittest.mock import patch, MagicMock

from data.data_source import DataSourceRouter, OfficialSource, FiveHundredSource
from data.data_fetcher import Draw


class TestOfficialSource:
    """测试官方数据源（用 mock 避免实际网络请求）"""

    def test_name(self):
        src = OfficialSource()
        assert src.name == "官方API"
        assert src.priority == 1

    def test_fetch_latest(self):
        """mock 网络请求测试"""
        src = OfficialSource()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "value": {
                "lastPoolDraw": {
                    "lotteryDrawNum": "26117",
                    "lotteryDrawTime": "2026-10-14",
                    "lotteryDrawResult": "04 13 19 29 31 02 12",
                },
                "list": [],
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(src.session, "get", return_value=mock_response):
            latest = src.fetch_latest()
            assert latest is not None
            assert latest.period == "26117"
            assert latest.front == [4, 13, 19, 29, 31]
            assert latest.back == [2, 12]


class TestRouterFallback:
    """测试路由器的自动降级"""

    def test_falls_back_to_next_source(self):
        """主源失败时切换备用"""
        router = DataSourceRouter(sources=[
            OfficialSource(),
            FiveHundredSource(),
        ])

        # mock 官方源失败，备用源成功
        official = router.sources[0]
        with patch.object(official, "fetch_latest", side_effect=Exception("主源失败")):
            # mock 备用源成功
            backup = router.sources[1]
            with patch.object(backup, "fetch_latest", return_value=Draw(
                period="2024001", draw_date="2024-01-01",
                front=[1, 2, 3, 4, 5], back=[3, 9]
            )):
                result = router.fetch_latest()
                assert result is not None
                assert result.period == "2024001"

    def test_stats_tracking(self):
        """调用统计应该正确更新"""
        router = DataSourceRouter(sources=[OfficialSource()])

        # mock 成功
        official = router.sources[0]
        with patch.object(official, "fetch_latest", return_value=Draw(
            period="2024001", draw_date="2024-01-01",
            front=[1, 2, 3, 4, 5], back=[3, 9]
        )):
            router.fetch_latest()
            stats = router.get_stats()
            assert stats["官方API"]["successes"] == 1
            assert stats["官方API"]["calls"] == 1

    def test_all_sources_fail(self):
        """所有源都失败时返回 None"""
        router = DataSourceRouter(sources=[OfficialSource(), FiveHundredSource()])

        for src in router.sources:
            with patch.object(src, "fetch_latest", side_effect=Exception("失败")):
                pass

        with patch.object(router.sources[0], "fetch_latest", side_effect=Exception("失败")):
            with patch.object(router.sources[1], "fetch_latest", side_effect=Exception("失败")):
                result = router.fetch_latest()
                assert result is None

    def test_priority_order(self):
        """数据源按优先级排序"""
        router = DataSourceRouter(sources=[
            FiveHundredSource(),  # priority=3
            OfficialSource(),      # priority=1
        ])
        # OfficialSource 应该在前面
        assert router.sources[0].name == "官方API"
        assert router.sources[1].name == "500彩票网"
