"""离线调试配对逻辑 (用已保存的 live_events.json, 不消耗 API 配额)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from data.jingcai_odds import fetch_matches
from scripts.live_scanner import SPORT_KEYS, code_in_name, match_matches

ev = json.load(open('data-raw/sports/live_events.json', encoding='utf-8'))
jc = fetch_matches()

by_key = {}
for e in ev:
    by_key.setdefault(e['sport_key'], []).append(e)

print('=== 逐联赛配对 ===')
total_ok = 0
total_jc = 0
for m in jc:
    k = SPORT_KEYS.get(m['league_cn'])
    if not k:
        print(f'  [无映射] {m["league_cn"]}')
        continue
    evs = by_key.get(k, [])
    total_jc += 1
    got = match_matches([m], evs)
    if got:
        total_ok += 1
        o = got[0]['ov']
        print(f'  ✓ {m["league_cn"]:<8} {m["home_cn"]}({m["home_en"]}) vs '
              f'{m["away_cn"]}({m["away_en"]})')
        print(f'      → {o["home_team"]} vs {o["away_team"]}  '
              f'({o.get("commence_time","")[11:16]}Z, {len(o.get("bookmakers",[]))} 家)')
    else:
        print(f'  ✗ {m["league_cn"]:<8} {m["home_cn"]}({m["home_en"]}) vs '
              f'{m["away_cn"]}({m["away_en"]})  未配对')

print()
print(f'配对率: {total_ok}/{total_jc} = {total_ok/total_jc*100 if total_jc else 0:.1f}%')
