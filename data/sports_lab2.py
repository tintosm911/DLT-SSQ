"""
竞彩分析聚合层 (Sports Lab)
===========================
把"抽水 / 套利 / 竞彩对比"三个层次合成一个可直接给 Web 用的结果.

数据来源:
  - 中国竞彩: data/jingcai_odds.py (webapi.sporttery.cn 实时, 官方免费)
  - 境外历史: data/sports_odds.py (football-data.co.uk GitHub 镜像, 真实赔率)

输出结构 (纯 dict, 可直接 JSON 化):
  {
    'ok': True,
    'leagues': [...],           # 各联赛分析
    'summary': {...},           # 汇总
    'jingcai': {...},           # 竞彩实时盘口 + 抽水
    'conclusion': '...'
  }
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from data.sports_arb import (analyze_arb, analyze_vig, backtest_arbs,
                             backtest_random, backtest_value_bets, devig,
                             implied_probabilities, vig)
from data.sports_odds import (CACHE_DIR, LEAGUE_DIRS, parse_season)

# 实测的中国竞彩抽水率 (2026-10-22, 24 场实时)
JINGCAI_VIG = 0.1291

# 只用真正独立的博彩公司
REAL_BOOKS = ['B365', 'Pinnacle', 'WilliamHill', 'Betfair', 'VCBet',
              'Interwetten', 'Ladbrokes']

# 5 大联赛 (代码 → 镜像目录)
BIG5 = {
    'premier-league': '英超',
    'la-liga': '西甲',
    'serie-a': '意甲',
    'bundesliga': '德甲',
    'ligue-1': '法甲',
}


# ============================================================
# 加载
# ============================================================
def load_league(league: str) -> List[Dict]:
    """加载某联赛本地缓存的全部赛季"""
    ms = []
    for f in sorted(CACHE_DIR.glob(f'{league}_*.csv')):
        try:
            ms.extend(parse_season(f.read_text(encoding='utf-8-sig')))
        except Exception:
            continue
    return ms


def leagues_available() -> List[str]:
    """本地有缓存的联赛"""
    out = []
    for lg in LEAGUE_DIRS:
        if list(CACHE_DIR.glob(f'{lg}_*.csv')):
            out.append(lg)
    return out


# ============================================================
# 单联赛分析
# ============================================================
def analyze_league(league: str, matches: Sequence[Dict],
                   min_profit: float = 0.005) -> Dict:
    """单个联赛的完整分析"""
    if not matches:
        return {'league': league, 'name': LEAGUE_DIRS.get(league, league),
                'matches': 0}

    vig_stats = analyze_vig(matches)
    real_books = [b for b in REAL_BOOKS if b in vig_stats]

    arb = analyze_arb(matches, real_books) if len(real_books) >= 3 else {
        'count': 0, 'checked': 0, 'rate': 0.0, 'max_profit': 0.0,
        'mean_profit': 0.0, 'best': None, 'arbs': []}
    arb_bt = backtest_arbs(matches, real_books, min_profit=min_profit) \
        if len(real_books) >= 3 else {}

    value = {}
    for b in ('Pinnacle', 'B365'):
        if b in vig_stats:
            value[b] = backtest_value_bets(matches, book=b)
    rand = {b: backtest_random(matches, book=b) for b in ('Pinnacle', 'B365')
            if b in vig_stats}

    # 竞彩 vs 境外 (用真实赔率 + 实测竞彩抽水模拟)
    jc_result = _jc_vs_overseas(matches, min_profit)

    best_vig = min(vig_stats.items(), key=lambda x: x[1]['mean']) \
        if vig_stats else (None, {'mean': 0})
    worst_vig = max(vig_stats.items(), key=lambda x: x[1]['mean']) \
        if vig_stats else (None, {'mean': 0})

    return {
        'league': league,
        'name': LEAGUE_DIRS.get(league, league),
        'matches': len(matches),
        'vig': vig_stats,
        'best_vig_book': best_vig[0],
        'best_vig': best_vig[1]['mean'] if best_vig[0] else 0,
        'worst_vig_book': worst_vig[0],
        'worst_vig': worst_vig[1]['mean'] if worst_vig[0] else 0,
        'arb': {k: v for k, v in arb.items() if k != 'arbs'},
        'arb_backtest': arb_bt,
        'value_bets': {k: {'roi': v.roi, 'bets': v.bets,
                           'hit_rate': v.hit_rate, 'clv': v.clv}
                       for k, v in value.items()},
        'random': {k: v['roi'] for k, v in rand.items()},
        'jingcai_vs': jc_result,
    }


def _jc_vs_overseas(matches: Sequence[Dict], min_profit: float) -> Dict:
    """
    竞彩 vs 境外: 用市场共识概率 + 实测竞彩抽水 反推竞彩赔率,
    然后比较"纯境外组合"与"含竞彩组合"的套利可行性.
    """
    import itertools

    found_pure = 0
    found_with = 0
    n_using_jc = 0
    checked = 0

    for m in matches:
        avail = {b: m['odds'][b] for b in REAL_BOOKS if b in m.get('odds', {})}
        if len(avail) < 2:
            continue
        checked += 1
        # ⚠ sports_arb.devig() 接受的是**概率数组**, 不是赔率数组!
        #   必须先 implied_probabilities() 转成隐含概率再 devig,
        #   否则把 (1.9, 4.2, 5.0) 归一化会得到荒谬的"共识概率",
        #   竞彩赔率被算成 5.18 而不是 1.77, 结论完全反过来.
        probs = np.mean([devig(implied_probabilities(o))
                         for o in avail.values()], axis=0)
        jc = tuple(1.0 / (p * (1.0 + JINGCAI_VIG)) for p in probs)

        best_pure = None
        best_with = None
        # ⚠ 三个结果必须来自**三个不同来源** —— 否则同一家公司同时出主胜和平局,
        #   会算出很小的 Σ(1/o) 假套利 (sports_arb.analyze_arb 也有同样约束)
        for combo in itertools.product(list(avail.items()), repeat=3):
            (b1, o1), (b2, o2), (b3, o3) = combo
            if b1 == b2 or b2 == b3 or b1 == b3:
                continue
            s = 1.0 / o1[0] + 1.0 / o2[1] + 1.0 / o3[2]
            if best_pure is None or s < best_pure:
                best_pure = s

        sides = [('竞彩', jc)] + list(avail.items())
        for combo in itertools.product(sides, repeat=3):
            (b1, o1), (b2, o2), (b3, o3) = combo
            if b1 == b2 or b2 == b3 or b1 == b3:
                continue
            s = 1.0 / o1[0] + 1.0 / o2[1] + 1.0 / o3[2]
            if best_with is None or s < best_with[0]:
                best_with = (s, (b1, b2, b3))

        if best_pure is not None and best_pure < 1.0 - min_profit:
            found_pure += 1
        if best_with and best_with[0] < 1.0 - min_profit:
            found_with += 1
            if '竞彩' in best_with[1]:
                n_using_jc += 1

    return {
        'checked': checked,
        'pure_count': found_pure,
        'pure_rate': found_pure / checked * 100 if checked else 0,
        'with_count': found_with,
        'with_rate': found_with / checked * 100 if checked else 0,
        'using_jingcai': n_using_jc,
        'jingcai_vig': JINGCAI_VIG,
    }


# ============================================================
# 竞彩实时盘口
# ============================================================
def analyze_jingcai_live(force_refresh: bool = False) -> Dict:
    """竞彩官方实时盘口 + 抽水分析"""
    from data.jingcai_odds import (analyze_vig as jc_vig, fetch_matches,
                                  load_cache, save_cache)

    if force_refresh:
        ms = fetch_matches()
        if ms:
            save_cache(ms)
    else:
        ms = load_cache()

    if not ms:
        return {'ok': False, 'error': '无竞彩数据 (先跑 fetch_matches)'}

    v = jc_vig(ms)
    return {
        'ok': True,
        'count': len(ms),
        'vig_mean': v.get('mean', 0),
        'vig_median': v.get('median', 0),
        'vig_min': v.get('min', 0),
        'vig_max': v.get('max', 0),
        'leagues': v.get('leagues', {}),
        'matches': [{
            'date': m['date'], 'time': m['time'],
            'league': m['league_cn'], 'league_slug': m['league_slug'],
            'home': m['home_cn'], 'away': m['away_cn'],
            'home_en': m['home_en'], 'away_en': m['away_en'],
            'had': m['had'], 'hhad': m['hhad'],
            'vig': (1 / m['had']['h'] + 1 / m['had']['d'] + 1 / m['had']['a'] - 1)
                   if all(m['had'].get(k) for k in ('h', 'd', 'a')) else None,
            'update': m.get('had_update', ''),
        } for m in ms],
    }


# ============================================================
# 汇总
# ============================================================
def run_sports_lab(leagues: Optional[List[str]] = None,
                   min_profit: float = 0.005,
                   include_jingcai: bool = True) -> Dict:
    """
    完整竞彩分析.

    leagues: None = 本地有缓存的所有联赛
    """
    leagues = leagues or leagues_available()
    if not leagues:
        return {'ok': False, 'error': '没有本地数据, 先跑 '
                                     'python scripts/sports_expectation.py --download'}

    results = []
    all_matches = []
    for lg in leagues:
        ms = load_league(lg)
        if not ms:
            continue
        all_matches.extend(ms)
        r = analyze_league(lg, ms, min_profit)
        results.append(r)

    if not results:
        return {'ok': False, 'error': '无有效数据'}

    # 全量汇总
    all_vig = {}
    for r in results:
        for k, v in r.get('vig', {}).items():
            all_vig.setdefault(k, []).append(v)
    vig_summary = {}
    for k, vs in all_vig.items():
        counts = [v['count'] for v in vs]
        means = [v['mean'] for v in vs]
        vig_summary[k] = {
            'count': sum(counts),
            'mean': float(np.mean(means)),
            'mean_by_league': means,
            'std_across_leagues': float(np.std(means)),
        }

    # 稳定性: 各联赛的套利结论是否一致
    arb_rates = [r['jingcai_vs']['pure_rate'] for r in results
                 if r.get('jingcai_vs', {}).get('checked')]
    using_jc = sum(r['jingcai_vs']['using_jingcai'] for r in results)

    out = {
        'ok': True,
        'leagues': results,
        'n_leagues': len(results),
        'n_matches': len(all_matches),
        'vig_summary': vig_summary,
        'stab': {
            'arb_rates': arb_rates,
            'arb_rate_min': min(arb_rates) if arb_rates else 0,
            'arb_rate_max': max(arb_rates) if arb_rates else 0,
            'arb_rate_std': float(np.std(arb_rates)) if arb_rates else 0,
            'using_jingcai_total': using_jc,
            'consistent': (max(arb_rates) - min(arb_rates) < 3.0) if arb_rates else False,
        },
        'conclusion': _conclusion(results, vig_summary, using_jc),
    }

    if include_jingcai:
        try:
            out['jingcai'] = analyze_jingcai_live()
        except Exception as e:
            out['jingcai'] = {'ok': False, 'error': str(e)}
    return out


def _conclusion(results, vig_summary, using_jc) -> str:
    parts = []
    real = {k: v for k, v in vig_summary.items() if k in REAL_BOOKS}
    if real:
        best = min(real.items(), key=lambda x: x[1]['mean'])
        worst = max(real.items(), key=lambda x: x[1]['mean'])
        parts.append(f'境外抽水 {best[0]} {best[1]["mean"]*100:.2f}% ~ '
                     f'{worst[0]} {worst[1]["mean"]*100:.2f}%')
    parts.append(f'中国竞彩抽水 {JINGCAI_VIG*100:.2f}% (实测)')
    if using_jc == 0:
        parts.append(f'{sum(r["jingcai_vs"]["checked"] for r in results)} 场扫描中, '
                     f'含竞彩的套利组合里竞彩用了 0 次')
    else:
        parts.append(f'含竞彩的套利组合中竞彩参与了 {using_jc} 次')
    rates = [r['jingcai_vs']['pure_rate'] for r in results
             if r.get('jingcai_vs', {}).get('checked')]
    if rates:
        parts.append(f'各联赛纯境外可套利率 {min(rates):.2f}%~{max(rates):.2f}%')
    return ' | '.join(parts)


__all__ = [
    'JINGCAI_VIG', 'REAL_BOOKS', 'BIG5',
    'load_league', 'leagues_available', 'analyze_league',
    'analyze_jingcai_live', 'run_sports_lab',
]
