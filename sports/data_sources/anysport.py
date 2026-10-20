"""
AnySport 数据源
================
接入 AnySport 商业体育数据 API (anysport.io)

API 能力:
  GET /v1/soccer/leagues        - 联赛列表
  GET /v1/soccer/matches        - 赛程 (按日期/联赛/球队)
  GET /v1/soccer/livescore      - 实时比分
  GET /v1/soccer/standings      - 积分榜
  GET /v1/soccer/odds/prematch  - 赛前赔率 (Pro+)
  GET /v1/soccer/odds/live      - 滚球赔率 (Pro Max)
  GET /v1/soccer/head2head      - 历史交锋
  GET /v1/soccer/teams          - 球队信息 (Basic+)
  GET /v1/soccer/players        - 球员信息 (Basic+)
  GET /v1/soccer/topscorers     - 射手榜 (Basic+)

套餐:
  Free Trial $0    120 calls/hour   基础 5 项
  Basic       $99  2,000 calls/hour +球员/球队/射手榜
  Pro        $199  10,000 calls/hour +赛前赔率
  Pro Max    $399  20,000 calls/hour +实时赔率 + WebSocket

认证: HTTP Header `apikey: YOUR_KEY` 或 `X-API-Key: YOUR_KEY`
"""
from __future__ import annotations
import os
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from ..config import LEAGUES, MATCH_OUTCOMES
from ..models import Match, Odds

logger = logging.getLogger(__name__)


# AnySport 联赛 ID → 我们的 LEAGUES.code 映射
# (需要从 AnySport /v1/soccer/leagues 实际拉取后填入)
LEAGUE_ID_MAP: Dict[str, str] = {
    # "asl_xxxxx": "epl",       # 英超
    # "asl_xxxxx": "laliga",    # 西甲
    # "asl_xxxxx": "seriea",    # 意甲
    # "asl_xxxxx": "bundesliga", # 德甲
    # "asl_xxxxx": "ligue1",    # 法甲
}


class AnySportSource:
    """AnySport 数据源实现 (非 stub)

    使用:
        source = AnySportSource(api_key="YOUR_KEY")
        matches = await source.fetch_matches("epl", "2024-2025")
    """

    name = "anysport"
    priority = 5  # 最高优先级 (Mock 是 fallback)

    BASE_URL = "https://data.anysport.io/v1/soccer"

    # API 限流 (calls/hour)
    RATE_LIMIT_PER_HOUR = 120  # Free Trial

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key or os.environ.get("ANYSPORT_API_KEY", "")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._calls_this_hour = 0
        self._hour_start = time.time()
        self._available = bool(self.api_key)

        if not self._available:
            logger.warning(
                "AnySport API key 未配置. 设置 ANYSPORT_API_KEY 环境变量 "
                "或在 AnySportSource(api_key='YOUR_KEY') 传入."
            )

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self._headers(),
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.api_key,
            "Accept": "application/json",
            "User-Agent": "sports-lab/0.1.0",
        }

    def _check_available(self):
        """确保 API key 已配置"""
        if not self._available:
            raise RuntimeError(
                "AnySport API key 未配置. 注册: https://dashboard.anysport.io/register "
                "然后设置 ANYSPORT_API_KEY 环境变量."
            )

    def _check_rate_limit(self):
        """简单的每小时限流追踪"""
        now = time.time()
        if now - self._hour_start > 3600:
            self._calls_this_hour = 0
            self._hour_start = now
        if self._calls_this_hour >= self.RATE_LIMIT_PER_HOUR:
            raise RuntimeError(
                f"已用满 {self.RATE_LIMIT_PER_HOUR} calls/hour 配额. "
                "等下小时重试或升级套餐."
            )
        self._calls_this_hour += 1

    async def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """HTTP GET with retry"""
        self._check_available()
        self._check_rate_limit()

        url = f"{self.BASE_URL}/{endpoint}"
        last_err = None

        for attempt in range(self.max_retries):
            try:
                if not self._client:
                    self._client = httpx.AsyncClient(
                        timeout=self.timeout,
                        headers=self._headers(),
                    )
                resp = await self._client.get(url, params=params or {})

                if resp.status_code == 401:
                    raise RuntimeError(
                        "AnySport API key 无效或过期. 检查 dashboard.anysport.io"
                    )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"AnySport API 失败 {self.max_retries} 次: {last_err}")

    # ============================================================
    # 公开 API (同步 wrapper for ease)
    # ============================================================
    def fetch_matches(self, league: str, season: str) -> List[Match]:
        """获取某联赛某赛季的所有比赛 (同步入口)"""
        self._check_available()  # 先确保 API key 已配置
        league_id = self._resolve_league_id(league)
        if not league_id:
            raise NotImplementedError(
                f"联赛 {league} 未配置 AnySport league_id. "
                f"请先调用 list_leagues() 获取 ID 后填入 LEAGUE_ID_MAP."
            )
        return asyncio.run(self._fetch_matches_async(league_id, season))

    def fetch_odds(self, match_ids: List[str]) -> List[Odds]:
        """获取赛前赔率 (同步入口)"""
        self._check_available()  # 先确保 API key 已配置
        return asyncio.run(self._fetch_prematch_odds_async(match_ids))

    async def _fetch_matches_async(self, league_id: str, season: str) -> List[Match]:
        """异步拉取所有比赛 (按页)"""
        all_matches: List[Match] = []
        page = 1
        limit = 100

        while True:
            data = await self._get("matches", {
                "league_id": league_id,
                "season": season,
                "page": page,
                "limit": limit,
                "lang": "zh",
            })
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                match = self._parse_match(item)
                if match:
                    all_matches.append(match)

            # 检查是否还有更多页
            meta = data.get("meta", {})
            if len(items) < limit or len(all_matches) >= meta.get("total", 0):
                break
            page += 1

        return all_matches

    async def _fetch_prematch_odds_async(self, match_ids: List[str]) -> List[Odds]:
        """异步拉取赛前赔率"""
        all_odds: List[Odds] = []
        # AnySport prematch 端点支持 match_id 过滤
        for match_id in match_ids:
            try:
                data = await self._get("odds/prematch", {
                    "match_id": match_id,
                    "lang": "zh",
                })
                for item in data.get("data", []):
                    odds = self._parse_prematch_odds(item)
                    if odds:
                        all_odds.append(odds)
            except Exception as e:
                logger.warning(f"拉取 {match_id} 赔率失败: {e}")

        return all_odds

    # ============================================================
    # 联赛 ID 解析
    # ============================================================
    async def list_leagues(self) -> List[Dict]:
        """获取所有联赛列表 (一次性, 用于填充 LEAGUE_ID_MAP)"""
        data = await self._get("leagues", {"lang": "zh"})
        return data.get("data", [])

    def _resolve_league_id(self, league: str) -> Optional[str]:
        """根据 LEAGUES.code 找 league_id (反向查找)"""
        for league_id, code in LEAGUE_ID_MAP.items():
            if code == league:
                return league_id
        return None

    # ============================================================
    # JSON → 我们的数据模型
    # ============================================================
    def _parse_match(self, item: Dict) -> Optional[Match]:
        """AnySport match JSON → Match"""
        try:
            # 状态判断
            status = item.get("status", "")
            started = item.get("started", False)
            finished = status.lower() in ("finished", "ft") or "finished" in status.lower()

            # 比分
            home_score = item.get("home_score")
            away_score = item.get("away_score")

            # 比赛结果
            outcome = None
            if finished and home_score is not None and away_score is not None:
                if home_score > away_score:
                    outcome = MATCH_OUTCOMES.HOME_WIN
                elif home_score < away_score:
                    outcome = MATCH_OUTCOMES.AWAY_WIN
                else:
                    outcome = MATCH_OUTCOMES.DRAW

            # 比赛时间 (UTC → 本地)
            utc_time = item.get("time_utc") or item.get("time")
            try:
                match_date = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
            except Exception:
                match_date = datetime.now(timezone.utc)

            league_code = LEAGUE_ID_MAP.get(item.get("league_id", ""), "epl")

            return Match(
                match_id=f"anysport_{item['match_id']}",
                league=league_code,
                season=str(item.get("season", "")),
                round_num=int(item.get("round", 0)) if item.get("round") else 0,
                match_date=match_date,
                home_team=item.get("home", {}).get("name", "Unknown"),
                away_team=item.get("away", {}).get("name", "Unknown"),
                home_score=home_score,
                away_score=away_score,
                outcome=outcome,
                status="finished" if finished else ("live" if started else "scheduled"),
            )
        except Exception as e:
            logger.warning(f"解析 match 失败: {e} | item={item}")
            return None

    def _parse_prematch_odds(self, item: Dict) -> Optional[Odds]:
        """AnySport prematch odds JSON → Odds"""
        try:
            main_market = item.get("main_market", "")
            if main_market != "match_winner":
                # 只关心胜平负市场
                return None

            home_odd = item.get("home_odd")
            draw_odd = item.get("draw_odd")
            away_odd = item.get("away_odd")

            if not all([home_odd, draw_odd, away_odd]):
                return None

            updated_at = item.get("updated_at", "")
            try:
                snapshot_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except Exception:
                snapshot_time = datetime.now(timezone.utc)

            return Odds(
                match_id=f"anysport_{item['match_id']}",
                bookmaker=item.get("bookmaker", "unknown"),
                snapshot_time=snapshot_time,
                home_odds=float(home_odd),
                draw_odds=float(draw_odd),
                away_odds=float(away_odd),
            )
        except Exception as e:
            logger.warning(f"解析 odds 失败: {e} | item={item}")
            return None

    async def health_check(self) -> bool:
        """健康检查: 调用一次 leagues 端点"""
        try:
            await self.list_leagues()
            return True
        except Exception as e:
            logger.warning(f"AnySport 健康检查失败: {e}")
            return False