"""
数据完整性审计
==============
检查本地开奖库的**完整性**与**连续性**, 输出可复现的审计报告。

审计三件事:
  A. 期数与期号连续性 —— 中间有没有缺期
  B. 相邻期开奖日期间隔 —— 是否符合正常开奖节奏 (是否有过长断层)
  C. 跨年衔接 —— 上一年末期到下一年首期是否连续

★ 背景: v2.5.0 时曾怀疑 DLT 库缺失 100 期 (按"每周一三五"排期推算),
  但审计证明**官方 API 的 total 与库存完全一致** (2938 期),
  缺失的是推算前提而不是数据本身。
  → 所以这个脚本的价值是: **用数据自己说话, 而不是靠猜**。

用法:
  python scripts/audit_data_integrity.py
  python scripts/audit_data_integrity.py --game dlt
"""
from __future__ import annotations

import argparse
import collections
import datetime
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import get_game

DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'

# 正常的开奖节奏: 相邻两期间隔的正常范围 (天)
NORMAL_GAP = (1, 4)
# 超过这个间隔就认为是"异常断层", 需要人工确认 (节假日/疫情停售)
GAP_ALERT = 7


def audit(game: str) -> dict:
    cfg = get_game(game)
    if not DB.exists():
        raise FileNotFoundError(f'数据库不存在: {DB}')

    conn = sqlite3.connect(str(DB))
    rows = list(conn.execute(
        'SELECT period, draw_date FROM draws WHERE game=? ORDER BY period',
        (game,)))
    conn.close()

    if not rows:
        return {'game': game, 'n': 0, 'error': '库内无数据'}

    periods = [r[0] for r in rows]
    dates = [datetime.date.fromisoformat(r[1]) for r in rows]
    period_set = set(periods)

    # --- 期号连续性 (按年内序号) ---
    by_year = collections.OrderedDict()
    for p in periods:
        by_year.setdefault(p[:4], []).append(p)
    gaps_in_seq = []
    for y, lst in by_year.items():
        seqs = sorted(int(p[4:]) for p in lst)
        for a, b in zip(seqs, seqs[1:]):
            if b != a + 1:
                gaps_in_seq.append((y, a, b))

    # --- 日期间隔分布 ---
    gap_dist = collections.Counter()
    big_gaps = []
    for i in range(1, len(dates)):
        g = (dates[i] - dates[i - 1]).days
        gap_dist[g] += 1
        if g > GAP_ALERT:
            big_gaps.append((periods[i - 1], dates[i - 1], periods[i], dates[i], g))

    # --- 跨年衔接 ---
    years = list(by_year.keys())
    year_jumps = []
    for i in range(len(years) - 1):
        y1, y2 = years[i], years[i + 1]
        last = dates[periods.index(by_year[y1][-1])]
        first = dates[periods.index(by_year[y2][0])]
        year_jumps.append((y1, y2, last, first, (first - last).days))

    # --- 每年期数 ---
    per_year = {y: len(v) for y, v in by_year.items()}

    return {
        'game': game,
        'name': cfg.name,
        'n': len(periods),
        'first': (periods[0], dates[0]),
        'last': (periods[-1], dates[-1]),
        'period_set': period_set,
        'per_year': per_year,
        'gaps_in_seq': gaps_in_seq,
        'gap_dist': dict(sorted(gap_dist.items())),
        'big_gaps': big_gaps,
        'year_jumps': year_jumps,
        'dates': dates,
        'periods': periods,
    }


def main():
    ap = argparse.ArgumentParser(description='数据完整性审计')
    ap.add_argument('--game', default=None,
                    help='不指定则审计全部彩种')
    args = ap.parse_args()

    games = [args.game] if args.game else ['dlt', 'ssq']
    all_ok = True

    for g in games:
        a = audit(g)
        print()
        print('=' * 76)
        print(f'  数据完整性审计 — {a["name"]} ({g})')
        print('=' * 76)
        if a.get('error'):
            print(f'  ❌ {a["error"]}')
            all_ok = False
            continue

        print(f'  期数        : {a["n"]:,}')
        print(f'  期号范围    : {a["first"][0]} ~ {a["last"][0]}')
        print(f'  日期范围    : {a["first"][1]} ~ {a["last"][1]}')
        print()

        # 每年期数
        print(f'  {"年":<8}{"期数":>7}   期号区间')
        for y, c in a['per_year'].items():
            lst = [p for p in a['periods'] if p.startswith(y)]
            print(f'  {y:<8}{c:>7}   {min(lst)} ~ {max(lst)}')
        print()

        # 期号连续性
        if a['gaps_in_seq']:
            print(f'  ⚠ 年内期号断层 {len(a["gaps_in_seq"])} 处:')
            for y, x, z in a['gaps_in_seq'][:20]:
                print(f'      {y}: {x:03d} → {z:03d}  (缺 {z - x - 1} 期)')
        else:
            print('  ✅ 年内期号完全连续 (无缺期)')
        print()

        # 日期间隔
        dist = a['gap_dist']
        normal = sum(v for k, v in dist.items() if NORMAL_GAP[0] <= k <= NORMAL_GAP[1])
        print(f'  相邻期间隔分布: ' + ', '.join(f'{k}天×{v}' for k, v in dist.items()))
        print(f'  正常节奏({NORMAL_GAP[0]}~{NORMAL_GAP[1]}天)占比: '
              f'{normal / a["n"] * 100:.2f}%')
        if a['big_gaps']:
            print(f'  >{GAP_ALERT} 天的断层 {len(a["big_gaps"])} 处 '
                  f'(预期为节假日休市 / 疫情停售):')
            for p1, d1, p2, d2, g in a['big_gaps']:
                print(f'      {p1}({d1}) → {p2}({d2})   {g} 天')
        else:
            print('  ✅ 无异常断层')
        print()

        # 跨年衔接
        bad = [(y1, y2, g) for y1, y2, _, _, g in a['year_jumps'] if g > GAP_ALERT]
        if bad:
            print(f'  ⚠ 跨年断层 {len(bad)} 处: ' +
                  ', '.join(f'{y1}→{y2}({g}天)' for y1, y2, g in bad))
        else:
            print('  ✅ 跨年衔接全部正常 (间隔 ≤ '
                  f'{max(g for *_, g in a["year_jumps"])} 天)')
        print()

        # 结论
        ok = not a['gaps_in_seq'] and not bad
        all_ok = all_ok and ok
        print(f'  结论: {"✅ 库完整, 无缺期" if ok else "❌ 存在缺期, 需排查采集器"}')

    print()
    print('=' * 76)
    print('  审计完成: ' + ('全部通过' if all_ok else '存在问题'))
    print('=' * 76)
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
