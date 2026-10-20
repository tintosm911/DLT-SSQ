"""
Elo 评分系统
===========
基于经典 Elo 算法的球队评分, 用于生成 fair_prob (真实概率估计)

公式:
  E_a = 1 / (1 + 10^((R_b - R_a - H)/400))   # 主场加成 H=LeagueConfig.avg_home_advantage
  R_a' = R_a + K * (S - E_a)
  其中 S=1 胜, 0.5 平, 0 负; K=LeagueConfig.elo_k_factor
"""
from __future__ import annotations
import math
from typing import Dict, List, Tuple, Optional

from .config import LEAGUES, MATCH_OUTCOMES
from .models import Match, TeamRating


class EloSystem:
    """Elo 球队评分系统"""

    def __init__(self, base_elo: float = 1500.0):
        self.base_elo = base_elo
        # key: (league, team) -> Elo
        self.ratings: Dict[Tuple[str, str], float] = {}
        # 比赛计数
        self.match_count: Dict[Tuple[str, str], int] = {}
        # 上次更新时间
        self.last_updated: Dict[Tuple[str, str], Optional[object]] = {}

    # ---------- 内部辅助 ----------
    def _get_rating(self, league: str, team: str) -> float:
        key = (league, team)
        if key not in self.ratings:
            self.ratings[key] = self.base_elo
            self.match_count[key] = 0
        return self.ratings[key]

    def _expected(self, rating_a: float, rating_b: float, home_advantage: float = 0.0) -> float:
        """Elo 期望胜率 (a vs b, a 主场有 home_advantage 优势)"""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a - home_advantage) / 400.0))

    # ---------- 公开接口 ----------
    def run_season(self, finished_matches: List[Match]) -> None:
        """
        跑完一个完整赛季, 累计更新 Elo 评分
        - 输入: 已结束的 Match 列表 (按时间顺序)
        - 输出: None, self.ratings 原地更新
        """
        for m in finished_matches:
            if not m.is_finished:
                continue
            league_cfg = LEAGUES.get(m.league)
            if league_cfg is None:
                continue
            k = league_cfg.elo_k_factor
            h_adv = league_cfg.avg_home_advantage

            r_home = self._get_rating(m.league, m.home_team)
            r_away = self._get_rating(m.league, m.away_team)

            # 期望胜率 (主主场)
            e_home = self._expected(r_home, r_away, home_advantage=h_adv)
            e_away = 1.0 - e_home

            # 实际得分
            if m.outcome == MATCH_OUTCOMES.HOME_WIN:
                s_home, s_away = 1.0, 0.0
            elif m.outcome == MATCH_OUTCOMES.AWAY_WIN:
                s_home, s_away = 0.0, 1.0
            else:  # DRAW
                s_home, s_away = 0.5, 0.5

            # 更新 Elo
            new_home = r_home + k * (s_home - e_home)
            new_away = r_away + k * (s_away - e_away)
            self.ratings[(m.league, m.home_team)] = new_home
            self.ratings[(m.league, m.away_team)] = new_away
            self.match_count[(m.league, m.home_team)] = self.match_count.get((m.league, m.home_team), 0) + 1
            self.match_count[(m.league, m.away_team)] = self.match_count.get((m.league, m.away_team), 0) + 1

    def predict(self, league: str, home_team: str, away_team: str) -> List[float]:
        """
        预测比赛三选一概率: [home_prob, draw_prob, away_prob]

        简化模型:
        - 用 Elo 期望胜率 e_home 作为主胜概率基础
        - 平局概率固定为 ~22% (业界经验值, 足球平均)
        - 主负 = 1 - p_home - p_draw
        """
        league_cfg = LEAGUES.get(league)
        h_adv = league_cfg.avg_home_advantage if league_cfg else 100.0
        r_home = self._get_rating(league, home_team)
        r_away = self._get_rating(league, away_team)
        e_home = self._expected(r_home, r_away, home_advantage=h_adv)

        # 简单映射: e_home -> [home, draw, away]
        # 平局概率: 主胜在 0.5 附近时最高
        p_home = e_home
        p_draw = 0.22 * (1.0 - abs(p_home - 0.5) * 1.5)  # 主胜越偏离 0.5, 平局越低
        p_draw = max(0.10, p_draw)
        p_away = 1.0 - p_home - p_draw
        # 防止负数
        if p_away < 0.05:
            p_away = 0.05
            p_home = min(p_home, 0.85)
            p_draw = 1.0 - p_home - p_away
        return [p_home, p_draw, p_away]

    def get_team_rating(self, league: str, team: str) -> float:
        return self._get_rating(league, team)

    def top_teams(self, league: str, n: int = 8) -> List[Tuple[str, float]]:
        """返回某联赛 Elo 排名前 N 的球队"""
        team_elos = [
            (team, elo)
            for (lg, team), elo in self.ratings.items()
            if lg == league
        ]
        team_elos.sort(key=lambda x: -x[1])
        return team_elos[:n]