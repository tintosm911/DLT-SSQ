"""离线重跑实时扫描 (用 live_events.json 缓存, 不消耗 API 配额)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from data.jingcai_odds import fetch_matches
from scripts.live_scanner import (SPORT_KEYS, bookmaker_odds, find_arbs,
                                 match_matches, print_report)

ev = json.load(open('data-raw/sports/live_events.json', encoding='utf-8'))
jc = fetch_matches()

by_key = {}
for e in ev:
    by_key.setdefault(e['sport_key'], []).append(e)

# 手动组装 run_live_scan 的结果 (离线版)
results = []
n_arb = 0
for m in jc:
    k = SPORT_KEYS.get(m['league_cn'])
    if not k:
        continue
    got = match_matches([m], by_key.get(k, []))
    if not got:
        continue
    e = got[0]['ov']
    jc_o = (m['had']['h'], m['had']['d'], m['had']['a'])
    books = bookmaker_odds(e)
    if not books:
        continue
    jc_vig = 1 / jc_o[0] + 1 / jc_o[1] + 1 / jc_o[2] - 1
    bv = {b: (1 / o[0] + 1 / o[1] + 1 / o[2] - 1) for b, o in books.items()}
    best = min(bv.items(), key=lambda x: x[1])
    arbs = find_arbs(jc_o, books, 0.0)
    if arbs:
        n_arb += 1
    results.append({
        'league': m['league_cn'], 'date': m['date'], 'time': m['time'],
        'home': m['home_cn'], 'away': m['away_cn'],
        'home_en': m['home_en'], 'away_en': m['away_en'],
        'jc_odds': jc_o, 'jc_vig': jc_vig,
        'ov_event': e['home_team'] + ' vs ' + e['away_team'],
        'ov_commence': e.get('commence_time'),
        'books': {b: list(o) for b, o in books.items()},
        'book_vigs': bv,
        'best_book': best[0], 'best_book_vig': best[1],
        'n_books': len(books),
        'arbs': arbs[:3],
    })

import numpy as np
all_bv = {}
for r in results:
    for b, v in r['book_vigs'].items():
        all_bv.setdefault(b, []).append(v)

r = {
    'ok': True,
    'scan_time': '离线缓存',
    'n_jc': len(jc), 'n_ov': len(ev), 'n_paired': len(results),
    'n_with_arb': n_arb,
    'jc_vig_mean': float(np.mean([x['jc_vig'] for x in results])) if results else 0,
    'book_vig_mean': {b: float(np.mean(v)) for b, v in all_bv.items()},
    'book_vig_best': min(all_bv.items(), key=lambda x: np.mean(x[1])) if all_bv else None,
    'best_arb': None,
    'matches': results,
}
for x in results:
    for a in x['arbs']:
        if r['best_arb'] is None or a['profit_pct'] > r['best_arb']['profit_pct']:
            r['best_arb'] = {**a, 'match': x}

print_report(r)

print('  每场博彩公司数:')
for x in results[:20]:
    print(f"    {x['league']:<8}{x['home']+'vs'+x['away']:<24} {x.get('n_books',0)} 家")
