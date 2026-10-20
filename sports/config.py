"""
竞彩配置中心
============
定义支持的联赛 + 比赛结果枚举
"""
from __future__ import annotations
from enum import IntEnum
from dataclasses import dataclass
from typing import Dict, List


class MATCH_OUTCOMES(IntEnum):
    """比赛三选一结果 (胜平负)"""
    HOME_WIN = 1  # 主胜
    DRAW = 0      # 平
    AWAY_WIN = -1 # 客胜


@dataclass
class LeagueConfig:
    """联赛配置"""
    code: str           # 内部代号
    name: str           # 中文名
    country: str        # 国家
    tier: int           # 等级 (1=顶级联赛)
    elo_k_factor: float = 20.0  # Elo K 因子 (主客场调整)
    avg_home_advantage: float = 100.0  # 主场优势 (Elo 分)


# 5大联赛 + 国际赛事
LEAGUES: Dict[str, LeagueConfig] = {
    "epl": LeagueConfig(
        code="epl", name="英超", country="England", tier=1,
        elo_k_factor=20.0, avg_home_advantage=100.0,
    ),
    "laliga": LeagueConfig(
        code="laliga", name="西甲", country="Spain", tier=1,
        elo_k_factor=20.0, avg_home_advantage=100.0,
    ),
    "seriea": LeagueConfig(
        code="seriea", name="意甲", country="Italy", tier=1,
        elo_k_factor=20.0, avg_home_advantage=100.0,
    ),
    "bundesliga": LeagueConfig(
        code="bundesliga", name="德甲", country="Germany", tier=1,
        elo_k_factor=20.0, avg_home_advantage=100.0,
    ),
    "ligue1": LeagueConfig(
        code="ligue1", name="法甲", country="France", tier=1,
        elo_k_factor=20.0, avg_home_advantage=100.0,
    ),
}


def list_leagues() -> List[str]:
    """列出所有支持的联赛"""
    return list(LEAGUES.keys())


def get_league(code: str) -> LeagueConfig:
    """获取联赛配置"""
    if code not in LEAGUES:
        raise ValueError(f"未知联赛: {code}, 可选: {list_leagues()}")
    return LEAGUES[code]