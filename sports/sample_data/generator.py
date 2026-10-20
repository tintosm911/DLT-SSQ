"""
示例数据生成器 - 5大联赛 2024-2025 赛季
=====================================
⚠️ 基于真实球队名 + 合理赔率/赛果分布的模拟数据
"""
from __future__ import annotations
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from sports.config import LEAGUES, MATCH_OUTCOMES
from sports.models import Match, Odds


# 5大联赛 2024-2025 真实球队名 (各 8 队, 缩小版)
TEAMS_2024_2025: Dict[str, List[str]] = {
    "epl": [
        "Manchester City", "Arsenal", "Liverpool", "Manchester United",
        "Chelsea", "Tottenham", "Newcastle", "Aston Villa",
    ],
    "laliga": [
        "Real Madrid", "Barcelona", "Atletico Madrid", "Girona",
        "Real Sociedad", "Athletic Bilbao", "Real Betis", "Villarreal",
    ],
    "seriea": [
        "Inter Milan", "AC Milan", "Juventus", "Napoli",
        "Atalanta", "Roma", "Lazio", "Fiorentina",
    ],
    "bundesliga": [
        "Bayer Leverkusen", "Bayern Munich", "Borussia Dortmund", "RB Leipzig",
        "Stuttgart", "Eintracht Frankfurt", "Hoffenheim", "Wolfsburg",
    ],
    "ligue1": [
        "Paris Saint-Germain", "Monaco", "Brest", "Lille",
        "Nice", "Lyon", "Marseille", "Lens",
    ],
}


# 球队基础 Elo
TEAM_BASE_ELO: Dict[Tuple[str, str], float] = {}

def _init_team_elos():
    elo_map = {
        # 英超
        ("epl", "Manchester City"): 1880, ("epl", "Arsenal"): 1860,
        ("epl", "Liverpool"): 1850, ("epl", "Manchester United"): 1750,
        ("epl", "Chelsea"): 1740, ("epl", "Tottenham"): 1730,
        ("epl", "Newcastle"): 1720, ("epl", "Aston Villa"): 1700,
        # 西甲
        ("laliga", "Real Madrid"): 1900, ("laliga", "Barcelona"): 1870,
        ("laliga", "Atletico Madrid"): 1820, ("laliga", "Girona"): 1750,
        ("laliga", "Real Sociedad"): 1740, ("laliga", "Athletic Bilbao"): 1720,
        ("laliga", "Real Betis"): 1710, ("laliga", "Villarreal"): 1720,
        # 意甲
        ("seriea", "Inter Milan"): 1860, ("seriea", "AC Milan"): 1810,
        ("seriea", "Juventus"): 1800, ("seriea", "Napoli"): 1780,
        ("seriea", "Atalanta"): 1770, ("seriea", "Roma"): 1760,
        ("seriea", "Lazio"): 1740, ("seriea", "Fiorentina"): 1730,
        # 德甲
        ("bundesliga", "Bayer Leverkusen"): 1870, ("bundesliga", "Bayern Munich"): 1880,
        ("bundesliga", "Borussia Dortmund"): 1790, ("bundesliga", "RB Leipzig"): 1770,
        ("bundesliga", "Stuttgart"): 1760, ("bundesliga", "Eintracht Frankfurt"): 1740,
        ("bundesliga", "Hoffenheim"): 1720, ("bundesliga", "Wolfsburg"): 1700,
        # 法甲
        ("ligue1", "Paris Saint-Germain"): 1900, ("ligue1", "Monaco"): 1780,
        ("ligue1", "Brest"): 1750, ("ligue1", "Lille"): 1740,
        ("ligue1", "Nice"): 1720, ("ligue1", "Lyon"): 1730,
        ("ligue1", "Marseille"): 1740, ("ligue1", "Lens"): 1720,
    }
    TEAM_BASE_ELO.update(elo_map)

_init_team_elos()


def generate_matches(league: str, season: str, n_rounds: int = 19, base_date: datetime = None) -> List[Match]:
    """生成一个联赛的 n_rounds 轮比赛"""
    teams = TEAMS_2024_2025[league]
    if base_date is None:
        base_date = datetime(2024, 8, 17)

    matches: List[Match] = []
    fixtures = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            fixtures.append((teams[i], teams[j]))
            fixtures.append((teams[j], teams[i]))

    selected = fixtures[:n_rounds * 4]
    round_size = 4

    for idx, (home, away) in enumerate(selected):
        round_num = idx // round_size + 1
        match_date = base_date + timedelta(days=round_num * 7 + idx % round_size)
        match_id = f"{league}_{season}_{home[:3].replace(' ', '')}{away[:3].replace(' ', '')}_r{round_num}"

        home_elo = TEAM_BASE_ELO.get((league, home), 1500) + 60
        away_elo = TEAM_BASE_ELO.get((league, away), 1500)
        elo_diff = home_elo - away_elo

        # 三选一概率 (基于 Elo 差, 平局率 ~27%)
        p_home = 1.0 / (1.0 + 10 ** (-elo_diff / 400.0))
        p_away = (1.0 - p_home) * 0.65
        p_draw = max(0.15, 1.0 - p_home - p_away)
        # 归一化
        s = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

        r = random.random()
        if r < p_home:
            outcome = MATCH_OUTCOMES.HOME_WIN
        elif r < p_home + p_draw:
            outcome = MATCH_OUTCOMES.DRAW
        else:
            outcome = MATCH_OUTCOMES.AWAY_WIN

        if outcome == MATCH_OUTCOMES.HOME_WIN:
            home_score = random.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]
            away_score = random.choices([0, 1, 2], weights=[60, 30, 10])[0]
            if home_score <= away_score:
                home_score = away_score + 1
        elif outcome == MATCH_OUTCOMES.AWAY_WIN:
            away_score = random.choices([1, 2, 3], weights=[50, 30, 10])[0]
            home_score = random.choices([0, 1, 2], weights=[60, 30, 10])[0]
            if away_score <= home_score:
                away_score = home_score + 1
        else:
            home_score = random.choices([0, 1, 2], weights=[30, 50, 20])[0]
            away_score = home_score

        matches.append(Match(
            match_id=match_id,
            league=league,
            season=season,
            round_num=round_num,
            match_date=match_date,
            home_team=home,
            away_team=away,
            home_score=home_score,
            away_score=away_score,
            outcome=outcome,
            status="finished",
        ))

    return matches


def generate_odds(match: Match) -> Odds:
    """为已结束比赛生成合理赔率 (基于赛果反推 + margin)"""
    if not match.is_finished:
        raise ValueError(f"比赛 {match.match_id} 未结束")

    home_elo = TEAM_BASE_ELO.get((match.league, match.home_team), 1500) + 60
    away_elo = TEAM_BASE_ELO.get((match.league, match.away_team), 1500)
    elo_diff = home_elo - away_elo

    p_home = 1.0 / (1.0 + 10 ** (-elo_diff / 400.0))
    p_away = (1.0 - p_home) * 0.65
    p_draw = max(0.15, 1.0 - p_home - p_away)
    s = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

    margin = 0.05
    fair_odds = {
        "home": 1.0 / p_home,
        "draw": 1.0 / p_draw,
        "away": 1.0 / p_away,
    }
    house_odds = {k: v * (1 - margin * 0.4) for k, v in fair_odds.items()}
    inv_sum = sum(1.0 / o for o in house_odds.values())
    target_sum = 1.0 + margin
    final_odds = {k: v * (inv_sum / target_sum) for k, v in house_odds.items()}
    final_odds = {k: max(1.05, min(50.0, v)) for k, v in final_odds.items()}

    return Odds(
        match_id=match.match_id,
        bookmaker="pinnacle",
        snapshot_time=match.match_date - timedelta(hours=2),
        home_odds=round(final_odds["home"], 2),
        draw_odds=round(final_odds["draw"], 2),
        away_odds=round(final_odds["away"], 2),
    )


def generate_demo_data(season: str = "2024-2025", n_rounds: int = 19) -> Dict:
    """生成完整 5大联赛演示数据"""
    random.seed(42)
    all_matches: List[Match] = []
    all_odds: List[Odds] = []
    for league in LEAGUES.keys():
        matches = generate_matches(league, season, n_rounds=n_rounds)
        odds = [generate_odds(m) for m in matches]
        all_matches.extend(matches)
        all_odds.extend(odds)
    return {
        "matches": all_matches,
        "odds": all_odds,
        "teams": TEAMS_2024_2025,
        "season": season,
    }


def save_demo_data(data: Dict, path: str = None):
    if path is None:
        path = Path(__file__).parent / "demo_2024_2025.json"
    else:
        path = Path(path)

    serializable = {
        "season": data["season"],
        "teams": data["teams"],
        "matches": [
            {**m.__dict__, "match_date": m.match_date.isoformat(),
             "outcome": int(m.outcome) if m.outcome is not None else None}
            for m in data["matches"]
        ],
        "odds": [
            {**o.__dict__, "snapshot_time": o.snapshot_time.isoformat()}
            for o in data["odds"]
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    return path


def load_demo_data(path: str = None) -> Dict:
    if path is None:
        path = Path(__file__).parent / "demo_2024_2025.json"
    else:
        path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
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
    return {
        "season": raw["season"],
        "teams": raw["teams"],
        "matches": matches,
        "odds": odds,
    }


if __name__ == "__main__":
    data = generate_demo_data()
    path = save_demo_data(data)
    print(f"✅ Saved {len(data['matches'])} matches to {path}")