"""
彩种配置中心 - 统一管理所有彩种的参数
====================================
支持彩种:
  - 大乐透 (DLT)
  - 双色球 (SSQ)

新增彩种只需在此添加配置 + 实现对应 DataSource
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class GameConfig:
    """彩种配置"""
    code: str               # 内部代号（小写）
    name: str               # 中文名
    game_id: str            # 官方 API game_id（如果适用）
    front_range: int        # 前区号码范围
    front_count: int        # 前区选几个
    back_range: int         # 后区号码范围
    back_count: int         # 后区选几个
    front_label: str        # 前区显示名
    back_label: str         # 后区显示名
    ticket_price: float     # 单注价格（元）
    front_color: str        # 前区配色（用于可视化）
    back_color: str         # 后区配色

    @property
    def total_combinations(self) -> int:
        """总组合数"""
        from math import comb
        return comb(self.front_range, self.front_count) * comb(self.back_range, self.back_count)


# ============================================================
# 已注册彩种
# ============================================================
GAMES: Dict[str, GameConfig] = {
    "dlt": GameConfig(
        code="dlt",
        name="超级大乐透",
        game_id="85",
        front_range=35,
        front_count=5,
        back_range=12,
        back_count=2,
        front_label="前区",
        back_label="后区",
        ticket_price=2.0,
        front_color="#dc2626",
        back_color="#3b82f6",
    ),
    "ssq": GameConfig(
        code="ssq",
        name="双色球",
        game_id="ssq",
        front_range=33,
        front_count=6,
        back_range=16,
        back_count=1,
        front_label="红球",
        back_label="蓝球",
        ticket_price=2.0,
        front_color="#dc2626",
        back_color="#2563eb",
    ),
}


def get_game(code: str = None) -> GameConfig:
    """获取彩种配置（默认大乐透）"""
    code = code or "dlt"
    if code not in GAMES:
        raise ValueError(f"未知彩种: {code}，可选: {list(GAMES.keys())}")
    return GAMES[code]


def list_games() -> List[str]:
    """列出所有彩种代号"""
    return list(GAMES.keys())


# ============================================================
# 双色球奖级规则（自 2026-01-14 调整后）
# ============================================================
SSQ_PRIZE_RULES = [
    ((6, 1), ("一等奖", 8000000, "浮动 ≥ 800 万")),
    ((6, 0), ("二等奖", 300000,  "浮动 ≈ 30 万")),
    ((5, 1), ("三等奖", 3000,    "固定 3000 元")),
    ((5, 0), ("四等奖", 200,     "固定 200 元")),
    ((4, 1), ("四等奖", 200,     "固定 200 元")),
    ((3, 1), ("五等奖", 10,      "固定 10 元")),
    ((4, 0), ("五等奖", 10,      "固定 10 元")),
    ((2, 1), ("六等奖", 5,       "固定 5 元")),
    ((1, 1), ("六等奖", 5,       "固定 5 元")),
    ((0, 1), ("六等奖", 5,       "固定 5 元")),
]


# ============================================================
# 大乐透奖级规则（兼容旧代码）
# ============================================================
DLT_PRIZE_RULES = [
    ((5, 2), ("一等奖", 8000000,  "浮动 ≈ 8000 万")),
    ((5, 1), ("二等奖", 300000,   "浮动 ≈ 30 万")),
    ((5, 0), ("三等奖", 10000,    "固定 10000 元")),
    ((4, 2), ("四等奖", 3000,     "固定 3000 元")),
    ((4, 1), ("五等奖", 300,      "固定 300 元")),
    ((4, 0), ("六等奖", 100,      "固定 100 元")),
    ((3, 2), ("七等奖", 200,      "固定 200 元")),
    ((3, 1), ("八等奖", 15,       "固定 15 元")),
    ((2, 2), ("八等奖", 15,       "固定 15 元")),
    ((3, 0), ("九等奖", 5,        "固定 5 元")),
    ((1, 2), ("九等奖", 5,        "固定 5 元")),
    ((0, 2), ("九等奖", 5,        "固定 5 元")),
]


PRIZE_RULES = {
    "dlt": DLT_PRIZE_RULES,
    "ssq": SSQ_PRIZE_RULES,
}


def get_prize_rules(code: str = None):
    """获取奖级规则"""
    code = code or "dlt"
    return PRIZE_RULES.get(code, [])