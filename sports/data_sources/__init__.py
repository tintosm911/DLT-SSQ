"""
数据源抽象层
==============

支持的数据源:
  1. AnySport  (商业 API, 优先级 5)  - 推荐, 但需 API key
  2. MockSource (本地示例数据, 优先级 999) - fallback, 无依赖

设计原则:
  - 与号码彩 data_source.py 一致的多源路由架构
  - 每个数据源一个类, 统一 fetch_matches() / fetch_odds()
  - 主源失败时自动降级到下一个
  - 公司网阻断爬虫时, MockSource 提供演示数据

配置:
  export ANYSPORT_API_KEY=your_key_here
  或在 AnySportSource(api_key='YOUR_KEY') 传入
"""
from __future__ import annotations
import os
import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 禁用代理 (绕过公司网代理)
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_SPY', 'all_spy']:
    os.environ.pop(k, None)

from ..config import LEAGUES, MATCH_OUTCOMES
from ..models import Match, Odds


class DataSource(ABC):
    """数据源抽象基类"""

    name: str = "default"
    priority: int = 100  # 越小优先级越高

    @abstractmethod
    def fetch_matches(self, league: str, season: str) -> List[Match]:
        """获取某联赛某赛季的所有比赛"""
        pass

    @abstractmethod
    def fetch_odds(self, match_ids: List[str]) -> List[Odds]:
        """获取指定比赛的赔率 (多家博彩公司)"""
        pass

    def health_check(self) -> bool:
        """健康检查"""
        try:
            test = self.fetch_matches("epl", "2024-2025")
            return len(test) > 0
        except Exception:
            return False


# ============================================================
# AnySport 数据源 (商业 API, 需 API key)
# ============================================================
from .anysport import AnySportSource


# ============================================================
# Mock 数据源 (基于已生成的 demo 数据)
# ============================================================
class MockSource(DataSource):
    """本地示例数据源 (用于演示和回测)"""

    name = "mock"
    priority = 999  # 最低优先级 (其他源失败时 fallback)

    def __init__(self, demo_json_path: str = None):
        if demo_json_path is None:
            demo_json_path = Path(__file__).parent.parent / "sample_data" / "demo_2024_2025.json"
        self.demo_json_path = Path(demo_json_path)
        self._cache = None

    def _load(self):
        if self._cache is None:
            with open(self.demo_json_path, "r", encoding="utf-8") as f:
                import json
                raw = json.load(f)

            matches = [
                Match(
                    **{k: v for k, v in m.items() if k not in ["match_date", "outcome"]},
                    match_date=datetime.fromisoformat(m["match_date"]),
                    outcome=MATCH_OUTCOMES(m["outcome"]) if m["outcome"] is not None else None,
                )
                for m in raw["matches"]
            ]
            odds = [
                Odds(
                    **{k: v for k, v in o.items() if k != "snapshot_time"},
                    snapshot_time=datetime.fromisoformat(o["snapshot_time"]),
                )
                for o in raw["odds"]
            ]
            self._cache = {"matches": matches, "odds": odds}
        return self._cache

    def fetch_matches(self, league: str, season: str) -> List[Match]:
        data = self._load()
        return [m for m in data["matches"] if m.league == league and m.season == season]

    def fetch_odds(self, match_ids: List[str]) -> List[Odds]:
        data = self._load()
        ids = set(match_ids)
        return [o for o in data["odds"] if o.match_id in ids]


# ============================================================
# 数据源路由器
# ============================================================
class DataSourceRouter:
    """多数据源路由器 (主源失败时降级)"""

    def __init__(self, anysport_api_key: str = None):
        self.sources: Dict[str, DataSource] = {}
        self._register_default_sources(anysport_api_key=anysport_api_key)

    def _register_default_sources(self, anysport_api_key: str = None):
        """注册默认数据源 (按优先级降序尝试)"""
        # 1. AnySport (商业 API, 需 key)
        try:
            self.register(AnySportSource(api_key=anysport_api_key))
        except Exception as e:
            pass  # 静默失败

        # 2. Mock 是最终 fallback
        self.register(MockSource())

    def register(self, source: DataSource):
        self.sources[source.name] = source

    def list_sources(self) -> List[str]:
        """列出所有已注册数据源"""
        return [s.name for s in sorted(self.sources.values(), key=lambda s: s.priority)]

    def fetch_matches(self, league: str, season: str) -> List[Match]:
        """按优先级尝试, 首个成功即返回"""
        sorted_sources = sorted(self.sources.values(), key=lambda s: s.priority)
        last_err = None
        for source in sorted_sources:
            try:
                matches = source.fetch_matches(league, season)
                if matches:
                    return matches
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"所有数据源失败. 最后错误: {last_err}")

    def fetch_odds(self, match_ids: List[str]) -> List[Odds]:
        sorted_sources = sorted(self.sources.values(), key=lambda s: s.priority)
        last_err = None
        for source in sorted_sources:
            try:
                odds = source.fetch_odds(match_ids)
                if odds:
                    return odds
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"所有数据源失败. 最后错误: {last_err}")