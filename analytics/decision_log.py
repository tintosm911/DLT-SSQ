"""
决策日志系统
============
记录每期推荐 + 自动回填开奖结果 + 9 奖级分类

数据流:
  1. recommend() 时记录: 期号 + 推荐号码 + 策略
  2. 开奖后自动回填: 实际号码 + 命中情况 + 奖级
  3. 输出: 命中率/ROI/盈亏分析

支持彩种: 大乐透 (9 奖级), 双色球 (6 奖级)
"""
from __future__ import annotations
import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

import pandas as pd

from data.games import get_prize_rules

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "decision_log.csv"


@dataclass
class DecisionLog:
    """单条决策日志"""
    timestamp: str                         # 推荐时间 (ISO)
    period: str                            # 期号
    game: str                              # 彩种
    strategy: str                          # 策略名
    front_picks: List[int]                 # 前区推荐号码
    back_picks: List[int]                  # 后区推荐号码
    front_actual: List[int] = field(default_factory=list)    # 前区实际
    back_actual: List[int] = field(default_factory=list)     # 后区实际
    front_hits: int = 0                    # 前区命中数
    back_hits: int = 0                     # 后区命中数
    prize_level: str = ""                  # 奖级 (如 "一等奖" / "未中")
    prize_money: float = 0.0               # 中奖金额
    roi_pct: float = 0.0                   # 该期 ROI
    filled_at: str = ""                    # 回填时间

    @property
    def won(self) -> bool:
        return self.prize_level not in ("", "未中", "未开奖")


def append_decision(log: DecisionLog) -> None:
    """追加一条决策记录到 CSV"""
    file_exists = LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "period", "game", "strategy",
                "front_picks", "back_picks",
                "front_actual", "back_actual",
                "front_hits", "back_hits",
                "prize_level", "prize_money", "roi_pct",
                "filled_at",
            ])
        writer.writerow([
            log.timestamp, log.period, log.game, log.strategy,
            ",".join(map(str, log.front_picks)),
            ",".join(map(str, log.back_picks)),
            ",".join(map(str, log.front_actual)),
            ",".join(map(str, log.back_actual)),
            log.front_hits, log.back_hits,
            log.prize_level, log.prize_money, log.roi_pct,
            log.filled_at,
        ])


def load_decisions(game: str = None) -> List[DecisionLog]:
    """加载历史决策日志"""
    if not LOG_FILE.exists():
        return []
    df = pd.read_csv(LOG_FILE)
    if game:
        df = df[df["game"] == game]

    decisions = []
    for _, row in df.iterrows():
        decisions.append(DecisionLog(
            timestamp=str(row.get("timestamp", "")),
            period=str(row.get("period", "")),
            game=str(row.get("game", "")),
            strategy=str(row.get("strategy", "")),
            front_picks=[int(x) for x in str(row.get("front_picks", "")).split(",") if x],
            back_picks=[int(x) for x in str(row.get("back_picks", "")).split(",") if x],
            front_actual=[int(x) for x in str(row.get("front_actual", "")).split(",") if x],
            back_actual=[int(x) for x in str(row.get("back_actual", "")).split(",") if x],
            front_hits=int(row.get("front_hits", 0)),
            back_hits=int(row.get("back_hits", 0)),
            prize_level=str(row.get("prize_level", "")),
            prize_money=float(row.get("prize_money", 0)),
            roi_pct=float(row.get("roi_pct", 0)),
            filled_at=str(row.get("filled_at", "")),
        ))
    return decisions


def fill_decisions_with_results(
    game: str = "dlt",
    period_data: Dict[str, Tuple[List[int], List[int]]] = None,
) -> int:
    """
    用实际开奖结果回填未结算的决策日志

    Args:
        game: 彩种
        period_data: {period: (front_actual, back_actual)}

    Returns: 回填条数
    """
    if period_data is None:
        period_data = {}

    decisions = load_decisions(game=game)
    filled_count = 0

    for dec in decisions:
        if dec.won:
            continue
        if dec.period not in period_data:
            continue

        front_actual, back_actual = period_data[dec.period]
        dec.front_actual = front_actual
        dec.back_actual = back_actual
        dec.front_hits = len(set(dec.front_picks) & set(front_actual))
        dec.back_hits = len(set(dec.back_picks) & set(back_actual))
        dec.filled_at = datetime.now().isoformat()

        # 查奖级
        prize_rules = get_prize_rules(game)
        for (f_req, b_req), (level, money, _) in prize_rules:
            if dec.front_hits == f_req and dec.back_hits == b_req:
                dec.prize_level = level
                dec.prize_money = money
                break
        else:
            dec.prize_level = "未中"
            dec.prize_money = 0

        # ROI (单注成本 2 元)
        cost = 2.0
        dec.roi_pct = (dec.prize_money - cost) / cost * 100
        filled_count += 1

    if filled_count > 0:
        # 重写整个 CSV (简单可靠)
        _rewrite_csv(decisions)
        logger.info(f"回填 {filled_count} 条决策")

    return filled_count


def _rewrite_csv(decisions: List[DecisionLog]) -> None:
    """重写整个决策日志 CSV"""
    if not decisions:
        return
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "period", "game", "strategy",
            "front_picks", "back_picks",
            "front_actual", "back_actual",
            "front_hits", "back_hits",
            "prize_level", "prize_money", "roi_pct",
            "filled_at",
        ])
        for d in decisions:
            writer.writerow([
                d.timestamp, d.period, d.game, d.strategy,
                ",".join(map(str, d.front_picks)),
                ",".join(map(str, d.back_picks)),
                ",".join(map(str, d.front_actual)),
                ",".join(map(str, d.back_actual)),
                d.front_hits, d.back_hits,
                d.prize_level, d.prize_money, d.roi_pct,
                d.filled_at,
            ])


def summary(game: str = "dlt") -> Dict:
    """汇总统计"""
    decisions = load_decisions(game=game)
    if not decisions:
        return {"n_decisions": 0}

    total = len(decisions)
    won = sum(1 for d in decisions if d.won)
    total_money = sum(d.prize_money for d in decisions)
    total_cost = total * 2.0  # 每期成本
    roi = (total_money - total_cost) / total_cost * 100 if total_cost > 0 else 0

    # 按奖级分布
    by_level = {}
    for d in decisions:
        by_level[d.prize_level] = by_level.get(d.prize_level, 0) + 1

    return {
        "n_decisions": total,
        "n_won": won,
        "win_rate": won / total if total > 0 else 0,
        "total_money": total_money,
        "total_cost": total_cost,
        "net_profit": total_money - total_cost,
        "roi_pct": roi,
        "by_level": by_level,
    }