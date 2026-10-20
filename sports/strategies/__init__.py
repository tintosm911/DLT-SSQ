"""
竞彩策略库
==========
- find_value_bets: 价值投注识别
- backtest_kelly:  凯利仓位 + 资金曲线回测
- find_best_parlays: 多场过关组合优化
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from ..config import MATCH_OUTCOMES
from ..models import Match, Odds, Bet, BetResult


# ============================================================
# Value Bet 数据类
# ============================================================
@dataclass
class ValueBet:
    """一个被识别为价值投注的机会"""
    match_id: str
    home_team: str
    away_team: str
    selection: MATCH_OUTCOMES          # 选哪个结果
    selection_label: str               # "主胜" / "平局" / "客胜"
    odds: float                        # 当时赔率
    fair_prob: float                   # 模型估计真实概率
    market_prob: float                 # 市场隐含概率 (去 margin 后)
    edge_pct: float                    # 价值差 = fair_prob - market_prob (百分点)
    kelly_fraction: float              # 凯利最优下注比例
    match_date: Optional[datetime] = None


@dataclass
class BacktestResult:
    """凯利回测结果"""
    n_bets: int
    n_wins: int
    n_losses: int
    hit_rate: float                    # 命中率
    total_staked: float
    total_returned: float
    net_profit: float
    roi: float                         # 净收益 / 总投入
    final_bankroll: float
    initial_bankroll: float
    bankroll_curve: List[float] = field(default_factory=list)


@dataclass
class Parlay:
    """一个组合 (过关)"""
    match_ids: List[str]
    selections: List[MATCH_OUTCOMES]
    combined_odds: float               # 各场赔率相乘
    combined_fair_prob: float          # 联合真实概率 (假设独立)
    expected_value: float              # EV = combined_fair_prob * combined_odds - 1
    picks: List[ValueBet] = field(default_factory=list)


# ============================================================
# 凯利公式
# ============================================================
def kelly_fraction(fair_prob: float, odds: float) -> float:
    """
    凯利最优下注比例: f* = (bp - q) / b
    其中:
      b = odds - 1  (净赔率)
      p = fair_prob
      q = 1 - p
    返回值 clip 到 [0, 1] (凯利可能为负, 代表不下注)
    """
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (b * fair_prob - (1.0 - fair_prob)) / b
    return max(0.0, min(1.0, f))


# ============================================================
# Value Bet 识别
# ============================================================
def find_value_bets(
    upcoming: List[Match],
    odds_list: List[Odds],
    fair_probs: Dict[str, Dict[MATCH_OUTCOMES, float]],
    min_edge_pct: float = 3.0,
) -> List[ValueBet]:
    """
    找出所有 edge_pct >= min_edge_pct 的价值投注

    参数:
      upcoming: 未完赛的比赛列表
      odds_list: Odds 对象列表 (同 upcoming 的 match_id)
      fair_probs: {match_id: {MATCH_OUTCOMES: fair_prob}}
      min_edge_pct: 最小 edge (百分点), 默认 3%

    返回: List[ValueBet], 按 edge_pct 降序
    """
    # 建 odds 索引: match_id -> first Odds
    odds_by_match: Dict[str, Odds] = {}
    for o in odds_list:
        if o.match_id not in odds_by_match:
            odds_by_match[o.match_id] = o

    picks: List[ValueBet] = []
    SEL_LABEL = {
        MATCH_OUTCOMES.HOME_WIN: "主胜",
        MATCH_OUTCOMES.DRAW: "平局",
        MATCH_OUTCOMES.AWAY_WIN: "客胜",
    }

    for m in upcoming:
        o = odds_by_match.get(m.match_id)
        if o is None:
            continue
        probs = fair_probs.get(m.match_id)
        if probs is None:
            continue
        # 市场隐含概率 (去 margin)
        market_probs = o.implied_probs(remove_margin=True)

        for sel, fair_p in probs.items():
            key = {MATCH_OUTCOMES.HOME_WIN: "home", MATCH_OUTCOMES.DRAW: "draw", MATCH_OUTCOMES.AWAY_WIN: "away"}[sel]
            market_p = market_probs.get(key, 0.0)
            if market_p <= 0:
                continue
            edge = (fair_p - market_p) * 100  # 百分点
            if edge < min_edge_pct:
                continue
            odds_v = {"home": o.home_odds, "draw": o.draw_odds, "away": o.away_odds}[key]
            kf = kelly_fraction(fair_p, odds_v)
            picks.append(ValueBet(
                match_id=m.match_id,
                home_team=m.home_team,
                away_team=m.away_team,
                selection=sel,
                selection_label=SEL_LABEL[sel],
                odds=odds_v,
                fair_prob=fair_p,
                market_prob=market_p,
                edge_pct=edge,
                kelly_fraction=kf,
                match_date=m.match_date,
            ))

    picks.sort(key=lambda v: -v.edge_pct)
    return picks


# ============================================================
# 凯利仓位回测
# ============================================================
def backtest_kelly(
    finished_matches: List[Match],
    historical_odds: List[Odds],
    fair_probs: Dict[str, Dict[MATCH_OUTCOMES, float]],
    initial_bankroll: float = 1000.0,
    min_edge_pct: float = 3.0,
    kelly_cap: float = 0.25,
) -> BacktestResult:
    """
    在已完赛的比赛上做凯利仓位回测
    - 找出 edge >= min_edge_pct 的投注机会
    - 按凯利比例 (clip 到 kelly_cap) 下注
    - 按实际结果结算

    返回 BacktestResult (含资金曲线)
    """
    bets: List[Bet] = []
    for m in finished_matches:
        if not m.is_finished:
            continue
        # 找到这场比赛的赔率
        o = next((oo for oo in historical_odds if oo.match_id == m.match_id), None)
        if o is None:
            continue
        probs = fair_probs.get(m.match_id)
        if probs is None:
            continue

        market_probs = o.implied_probs(remove_margin=True)
        for sel, fair_p in probs.items():
            key = {MATCH_OUTCOMES.HOME_WIN: "home", MATCH_OUTCOMES.DRAW: "draw", MATCH_OUTCOMES.AWAY_WIN: "away"}[sel]
            market_p = market_probs.get(key, 0.0)
            edge = (fair_p - market_p) * 100
            if edge < min_edge_pct:
                continue
            odds_v = {"home": o.home_odds, "draw": o.draw_odds, "away": o.away_odds}[key]
            kf = kelly_fraction(fair_p, odds_v)
            kf = min(kf, kelly_cap)
            if kf <= 0:
                continue
            bets.append(Bet(
                bet_id=f"{m.match_id}_{MATCH_OUTCOMES(sel).name}",
                match_id=m.match_id,
                bookmaker=o.bookmaker,
                selection=sel,
                odds=odds_v,
                stake=0.0,  # 后面按资金曲线动态算
                fair_prob=fair_p,
                market_prob=market_p,
                edge=edge / 100.0,
                kelly_fraction=kf,
            ))

    # 走资金曲线
    bankroll = initial_bankroll
    curve = [bankroll]
    n_wins = 0
    n_losses = 0
    total_staked = 0.0
    total_returned = 0.0

    # 建立 match_id -> match 映射
    match_map = {m.match_id: m for m in finished_matches}

    for b in bets:
        m = match_map.get(b.match_id)
        if m is None or not m.is_finished:
            continue
        stake = bankroll * b.kelly_fraction
        if stake <= 0:
            continue
        b.stake = stake
        total_staked += stake
        won = (m.outcome == b.selection)
        if won:
            n_wins += 1
            profit = stake * (b.odds - 1.0)
            bankroll += profit
            total_returned += stake + profit
        else:
            n_losses += 1
            bankroll -= stake
        curve.append(bankroll)

    return BacktestResult(
        n_bets=len(bets),
        n_wins=n_wins,
        n_losses=n_losses,
        hit_rate=(n_wins / max(1, len(bets))),
        total_staked=total_staked,
        total_returned=total_returned,
        net_profit=bankroll - initial_bankroll,
        roi=(bankroll - initial_bankroll) / max(1e-9, total_staked),
        final_bankroll=bankroll,
        initial_bankroll=initial_bankroll,
        bankroll_curve=curve,
    )


# ============================================================
# 组合 (过关) 优化
# ============================================================
def find_best_parlays(
    value_picks: List[ValueBet],
    min_legs: int = 2,
    max_legs: int = 4,
    max_parlays: int = 10,
    min_ev: float = 0.0,
) -> List[Parlay]:
    """
    从 Value Bet 池中枚举组合, 找出 EV 最高的过关
    - min_legs / max_legs: 组合的最小/最大场数
    - max_parlays: 返回的最多组合数
    - min_ev: 最小期望值 (EV = fair_prob * combined_odds - 1), 默认 0

    注意: 同一场比赛只能选一个结果 (去重)
    """
    # 按 match_id 分组
    by_match: Dict[str, List[ValueBet]] = {}
    for v in value_picks:
        by_match.setdefault(v.match_id, []).append(v)

    match_ids = list(by_match.keys())
    parlays: List[Parlay] = []

    for n_legs in range(min_legs, max_legs + 1):
        if len(match_ids) < n_legs:
            continue
        for combo in combinations(match_ids, n_legs):
            # 每场比赛选 edge 最大的一个结果
            legs = []
            for mid in combo:
                best = max(by_match[mid], key=lambda v: v.edge_pct)
                legs.append(best)
            combined_odds = 1.0
            for leg in legs:
                combined_odds *= leg.odds
            combined_fair = 1.0
            for leg in legs:
                combined_fair *= leg.fair_prob
            ev = combined_fair * combined_odds - 1.0
            if ev < min_ev:
                continue
            parlays.append(Parlay(
                match_ids=[l.match_id for l in legs],
                selections=[l.selection for l in legs],
                combined_odds=combined_odds,
                combined_fair_prob=combined_fair,
                expected_value=ev,
                picks=legs,
            ))

    parlays.sort(key=lambda p: -p.expected_value)
    return parlays[:max_parlays]


__all__ = [
    "ValueBet",
    "BacktestResult",
    "Parlay",
    "kelly_fraction",
    "find_value_bets",
    "backtest_kelly",
    "find_best_parlays",
]