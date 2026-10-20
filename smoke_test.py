"""端到端冒烟测试"""
import sys, time
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "third_party"))

print('=== 端到端冒烟测试 ===')
print()

# 1. Number core
t0 = time.time()
from core import compute_all_heat_scores
from core import FrequencyAlgorithm, BayesianAlgorithm, ZScoreAlgorithm
print(f'1. core 7 算法        : {time.time()-t0:.2f}s')

# 2. Data layer
t0 = time.time()
from data import load_lottery_data
from data.sqlite_storage import SQLiteStorage
from data.games import get_game, GAMES
print(f'2. data 层            : {time.time()-t0:.2f}s')

# 3. Analytics
t0 = time.time()
from analytics import recommender, strategy_backtest, decision_log
from analytics.probability_lab import step13_drawscope_integration, run_full_lab, step6_chi2_independence
print(f'3. analytics 7 模块   : {time.time()-t0:.2f}s')

# 4. Sports (rebuilt)
t0 = time.time()
from sports.elo import EloSystem
from sports.strategies import find_value_bets, backtest_kelly, find_best_parlays
from sports.data_sources import DataSourceRouter
print(f'4. sports (rebuilt)   : {time.time()-t0:.2f}s')

# 5. DrawScope
t0 = time.time()
from drawscope_engine.statistics.analytics import analyze, SIGNALS, DISCLAIMERS
from sports.drawscope_adapter import dlt_df_to_drawings, ssq_df_to_drawings, dlt_payload, ssq_payload
print(f'5. DrawScope 引擎     : {time.time()-t0:.2f}s, {len(SIGNALS)} 信号, {len(DISCLAIMERS)} 免责')

# 6. End-to-end: Step 13 with synthetic DLT
import numpy as np
import pandas as pd
from datetime import date, timedelta
np.random.seed(42)
n = 100
base = date(2024, 1, 1)
matches = []
for i in range(n):
    f = sorted(np.random.choice(range(1, 36), 5, replace=False).tolist())
    b = sorted(np.random.choice(range(1, 13), 2, replace=False).tolist())
    matches.append({'draw_date': (base + timedelta(days=i*3)).isoformat(), 'front': f, 'back': b})

t0 = time.time()
result = step13_drawscope_integration(matches, game='dlt')
chi_dlt = result.get('chi_square')
print(f'6. Step 13 (DLT, {n}期): {time.time()-t0:.2f}s, chi2={chi_dlt:.2f}')

# SSQ: 6 红 + 1 蓝
matches_ssq = []
for i in range(80):
    f = sorted(np.random.choice(range(1, 34), 6, replace=False).tolist())
    b = sorted(np.random.choice(range(1, 17), 1, replace=False).tolist())
    matches_ssq.append({'draw_date': (base + timedelta(days=i*3)).isoformat(), 'front': f, 'back': b})

t0 = time.time()
result_ssq = step13_drawscope_integration(matches_ssq, game='ssq')
chi_ssq = result_ssq.get('chi_square')
print(f'7. Step 13 (SSQ, 80期): {time.time()-t0:.2f}s, chi2={chi_ssq:.2f}')

# 8. Sports end-to-end
t0 = time.time()
router = DataSourceRouter()
matches_data = router.fetch_matches('epl', '2024-2025')
print(f'8. sports 数据加载    : {time.time()-t0:.2f}s, {len(matches_data)} 场')

t0 = time.time()
finished = [m for m in matches_data if m.is_finished]
elo = EloSystem()
elo.run_season(finished)
print(f'9. Elo 训练           : {time.time()-t0:.2f}s, {len(elo.ratings)} 队')

t0 = time.time()
odds_list = router.fetch_odds([m.match_id for m in matches_data])
fair_probs = {m.match_id: dict(zip([1, 0, -1], elo.predict(m.league, m.home_team, m.away_team))) for m in matches_data}
picks = find_value_bets(matches_data, odds_list, fair_probs, min_edge_pct=2.0)
print(f'10. Value Bet 识别     : {time.time()-t0:.2f}s, {len(picks)} 个')

t0 = time.time()
bt = backtest_kelly(finished, odds_list, fair_probs, initial_bankroll=1000.0, min_edge_pct=2.0)
print(f'11. 凯利回测          : {time.time()-t0:.2f}s, ROI={bt.roi*100:+.2f}%')

t0 = time.time()
parlays = find_best_parlays(picks, min_legs=2, max_legs=3, max_parlays=5)
print(f'12. 组合优化          : {time.time()-t0:.2f}s, {len(parlays)} 个')

print()
print('=== 全部冒烟通过 ✓ ===')