"""
竞彩实验室端到端入口
====================
1. 加载示例数据 (5大联赛 2024-2025)
2. 用 Elo 跑完已结束比赛 → 得到球队评分
3. 对未来比赛预测 fair_prob
4. 找 Value Bet
5. 凯利仓位回测
6. 组合 (过关) 优化

用法:
  python scripts/sports_lab.py
  python scripts/sports_lab.py --league epl --min-edge 3.0
"""
from __future__ import annotations
import sys
import io

# 强制 UTF-8 (Windows GBK 终端)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sports.config import LEAGUES, MATCH_OUTCOMES
from sports.data_sources import DataSourceRouter
from sports.elo import EloSystem
from sports.models import Match
from sports.strategies import (
    find_value_bets,
    backtest_kelly,
    find_best_parlays,
)


def section(title: str, char: str = "="):
    print()
    print(char * 80)
    print(f"  {title}")
    print(char * 80)


def load_data(league: str = "epl", season: str = "2024-2025"):
    """加载数据 (AnySport → Mock fallback)"""
    router = DataSourceRouter()
    matches = router.fetch_matches(league, season)
    odds_list = router.fetch_odds([m.match_id for m in matches])
    return matches, odds_list


def split_finished_upcoming(matches: List[Match]):
    finished = [m for m in matches if m.is_finished]
    upcoming = [m for m in matches if not m.is_finished]
    return finished, upcoming


def build_fair_probs(elo: EloSystem, matches: List[Match]) -> Dict[str, Dict[MATCH_OUTCOMES, float]]:
    """用 Elo 给每场比赛生成 fair_prob"""
    out = {}
    for m in matches:
        p_home, p_draw, p_away = elo.predict(m.league, m.home_team, m.away_team)
        out[m.match_id] = {
            MATCH_OUTCOMES.HOME_WIN: p_home,
            MATCH_OUTCOMES.DRAW: p_draw,
            MATCH_OUTCOMES.AWAY_WIN: p_away,
        }
    return out


def main(league: str = "epl", min_edge: float = 3.0):
    section(f"竞彩实验室 (Sports Betting Lab) | {LEAGUES[league].name} {league}", "#")

    # 1) 加载数据
    section("Step 1 · 数据加载")
    matches, odds_list = load_data(league, "2024-2025")
    print(f"  ✅ 加载 {len(matches)} 场比赛, {len(odds_list)} 条赔率")

    finished, upcoming = split_finished_upcoming(matches)
    print(f"     已结束: {len(finished)} | 未完赛: {len(upcoming)}")

    # 2) Elo 评分
    section("Step 2 · Elo 评分 (基于已结束比赛)")
    elo = EloSystem()
    elo.run_season(finished)
    print(f"  ✅ Elo 评分更新: {len(elo.ratings)} 支球队")
    print(f"     前 5:")
    for team, rating in elo.top_teams(league, 5):
        print(f"       {team:30s}  Elo={rating:.0f}")

    # 3) fair_prob
    section("Step 3 · fair_prob 估计 (Elo)")
    fair_probs_all = build_fair_probs(elo, matches)
    print(f"  ✅ 生成 {len(fair_probs_all)} 场比赛的三选一概率")

    # 4) Value Bet 识别
    section(f"Step 4 · Value Bet 识别 (min_edge = {min_edge}%)")
    picks = find_value_bets(upcoming, odds_list, fair_probs_all, min_edge_pct=min_edge)
    print(f"  ✅ 找到 {len(picks)} 个 Value Bet")
    for i, p in enumerate(picks[:8], 1):
        print(f"     {i}. {p.home_team} vs {p.away_team} | "
              f"{p.selection_label} @ {p.odds:.2f} | "
              f"fair={p.fair_prob:.3f} market={p.market_prob:.3f} | "
              f"edge={p.edge_pct:+.2f}% | kelly={p.kelly_fraction*100:.2f}%")

    # 5) 凯利回测 (在已结束比赛上模拟)
    section("Step 5 · 凯利仓位回测 (回看 finished)")
    bt = backtest_kelly(
        finished, odds_list, fair_probs_all,
        initial_bankroll=1000.0,
        min_edge_pct=min_edge,
        kelly_cap=0.25,
    )
    print(f"  ✅ 下注 {bt.n_bets} 场 ({bt.n_wins}胜 / {bt.n_losses}负)")
    print(f"     命中率:    {bt.hit_rate*100:.1f}%")
    print(f"     总投入:    {bt.total_staked:.2f}")
    print(f"     净收益:    {bt.net_profit:+.2f}")
    print(f"     ROI:       {bt.roi*100:+.2f}%")
    print(f"     终值资金:  {bt.final_bankroll:.2f} (从 {bt.initial_bankroll:.0f} 起步)")

    # 6) 组合优化
    section("Step 6 · 组合 (过关) 优化")
    parlays = find_best_parlays(picks, min_legs=2, max_legs=3, max_parlays=5, min_ev=0.0)
    print(f"  ✅ 找到 {len(parlays)} 个有正 EV 的组合")
    for i, p in enumerate(parlays[:5], 1):
        legs_str = " + ".join(f"{v.home_team[:8]}..{v.away_team[:8]} {v.selection_label}" for v in p.picks)
        print(f"     {i}. {len(p.picks)} 场 | 组合赔率={p.combined_odds:.2f} | "
              f"fair={p.combined_fair_prob:.3f} | EV={p.expected_value*100:+.2f}%")
        print(f"        腿: {legs_str}")

    section("★ 总结 ★", "#")
    print()
    print(f"  1. {LEAGUES[league].name} 已结束 {len(finished)} 场, 未完赛 {len(upcoming)} 场")
    print(f"  2. Elo 前 5 强评分已生成")
    print(f"  3. 找到 {len(picks)} 个 Value Bet (edge ≥ {min_edge}%)")
    print(f"  4. 凯利回测: {bt.n_bets} 场, ROI={bt.roi*100:+.2f}%")
    print(f"  5. 组合优化: {len(parlays)} 个有正 EV 的过关")
    print()
    print("  → 与号码彩的根本区别:")
    print("     - 号码彩期望必负 (凯利=0)")
    print("     - 竞彩期望可正 (凯利可>0), 前提是 fair_prob > market_prob")
    print("  → Elo 不是估值基准, 仅作为 fair_prob 估计")
    print()
    print("  结论: Value Bet + 凯利仓位 = 系统化优势, 但仍需严谨 bankroll 管理")


if __name__ == "__main__":
    league = "epl"
    min_edge = 3.0
    if "--league" in sys.argv:
        idx = sys.argv.index("--league")
        if idx + 1 < len(sys.argv):
            league = sys.argv[idx + 1]
    if "--min-edge" in sys.argv:
        idx = sys.argv.index("--min-edge")
        if idx + 1 < len(sys.argv):
            min_edge = float(sys.argv[idx + 1])
    main(league=league, min_edge=min_edge)