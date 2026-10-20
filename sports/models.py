"""
竞彩数据模型
===========
所有数据类的统一 schema, 让 DataSource / 策略 / 回测模块解耦
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from .config import MATCH_OUTCOMES


@dataclass
class Match:
    """一场比赛"""
    match_id: str                       # 全局唯一 ID, 如 "epl_2024_arsche_1"
    league: str                         # 联赛 code
    season: str                         # 赛季, 如 "2024-2025"
    round_num: int                      # 轮次 (1, 2, ...)
    match_date: datetime                # 比赛时间
    home_team: str                      # 主队名
    away_team: str                      # 客队名
    home_score: Optional[int] = None    # 主队比分 (赛后填充)
    away_score: Optional[int] = None    # 客队比分 (赛后填充)
    outcome: Optional[MATCH_OUTCOMES] = None  # 赛果 (赛后填充)
    status: str = "scheduled"           # scheduled / finished / live

    @property
    def is_finished(self) -> bool:
        return self.status == "finished" and self.outcome is not None


@dataclass
class Odds:
    """一场比赛的一组赔率 (单家博彩公司一个时间点)"""
    match_id: str
    bookmaker: str                      # 博彩公司, 如 "bet365" / "pinnacle"
    snapshot_time: datetime             # 抓取时间
    home_odds: float                    # 主胜赔率
    draw_odds: float                    # 平赔率
    away_odds: float                    # 客胜赔率

    def implied_probs(self, remove_margin: bool = True) -> Dict[str, float]:
        """
        反推隐含概率 (含/不含 margin)

        不去 margin:
            p_i = 1 / odds_i
            三者之和 = 1 + margin (margin = 庄家利润)

        去 margin (概率归一化):
            p_i = (1 / odds_i) / Σ(1/odds_j)
            三者之和 = 1.0
        """
        inv = {
            "home": 1.0 / self.home_odds,
            "draw": 1.0 / self.draw_odds,
            "away": 1.0 / self.away_odds,
        }
        if remove_margin:
            total = sum(inv.values())
            return {k: v / total for k, v in inv.items()}
        return inv

    def margin(self) -> float:
        """博彩公司利润 (overround)"""
        return sum(1.0 / o for o in [self.home_odds, self.draw_odds, self.away_odds]) - 1.0


@dataclass
class TeamRating:
    """球队评分 (Elo)"""
    team: str
    league: str
    elo: float = 1500.0                 # 标准起始分
    n_matches: int = 0
    last_updated: Optional[datetime] = None


@dataclass
class Bet:
    """一次下注"""
    bet_id: str
    match_id: str
    bookmaker: str
    selection: MATCH_OUTCOMES           # 选哪个结果
    odds: float                         # 当时的赔率
    stake: float                        # 投入金额
    fair_prob: float                    # 当时估计的真实概率
    market_prob: float                  # 市场隐含概率
    edge: float                         # 价值差 = fair_prob - market_prob
    kelly_fraction: float               # 凯利最优比例
    placed_at: datetime = field(default_factory=datetime.now)

    @property
    def is_value_bet(self) -> bool:
        """是否被识别为 Value Bet (edge > 0)"""
        return self.edge > 0

    def potential_profit(self) -> float:
        """最大盈利 (不含本金)"""
        return self.stake * (self.odds - 1)


@dataclass
class BetResult:
    """下注结果 (回填)"""
    bet_id: str
    actual_outcome: MATCH_OUTCOMES
    won: bool
    profit: float                       # 正=赢, 负=输
    bankroll_after: float               # 结算后资金
    settled_at: datetime = field(default_factory=datetime.now)