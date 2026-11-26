"""
联合全灭概率 · 历史实测复核 (用真实开奖数据验证枚举结果)
===========================================================
★ 为什么要两个口径:
  `scripts/joint_miss_prob.py` 是**全枚举** —— 对 C(35,5)×C(12,2) = 21,425,712
  种开奖组合逐个判定, 得到理论概率。
  本脚本是**历史实测** —— 把同一套方案套到本地库的每一期真实开奖上,
  统计实际发生了多少次。

  两条路完全独立 (一个算、一个数)。吻合 → 双方都对; 不吻合 → 有一方错了。
  ★ v3.3.3 首版就是靠这个思路才发现联合枚举的 bug (报 91.17%,
    而历史实测只有 25%)。

用法:
  python scripts/hist_miss_rate.py                     # 最近一期已结算的实买方案
  python scripts/hist_miss_rate.py --period 2026135
  python scripts/hist_miss_rate.py --all
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import normalize_period

DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'


def win_cond(f: int, b: int) -> bool:
    """大乐透: 前区命中 f、后区命中 b → 是否中奖"""
    if f >= 3:
        return True
    if f == 2 and b >= 1:
        return True
    if f == 1 and b == 2:
        return True
    if f == 0 and b == 2:
        return True
    return False


def load_draws(game='dlt'):
    if not DB.exists():
        return []
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    try:
        rows = list(cur.execute(
            'SELECT period, draw_date, front_numbers, back_numbers '
            'FROM draws WHERE game=? ORDER BY period', (game,)))
    except sqlite3.Error:
        rows = []
    con.close()
    out = []
    for period, date, front, back in rows:
        f = _nums(front)
        b = _nums(back)
        if len(f) == 5 and len(b) == 2:
            out.append((normalize_period(str(period), 'dlt'), date,
                        sorted(f), sorted(b)))
    return out


def _nums(blob):
    import json
    if blob is None:
        return []
    if isinstance(blob, (list, tuple)):
        return [int(x) for x in blob]
    s = str(blob).strip()
    if s.startswith('['):
        try:
            return [int(x) for x in json.loads(s)]
        except Exception:
            pass
    return [int(x) for x in s.replace('[', ' ').replace(']', ' ')
            .replace(',', ' ').split() if x.isdigit()]


def expand(p):
    out = []
    for fc in combinations(p['front_tuo'], 5 - len(p['front_dan'])):
        for bc in combinations(p['back_tuo'], 2 - len(p['back_dan'])):
            out.append((tuple(sorted(list(p['front_dan']) + list(fc))),
                        tuple(sorted(list(p['back_dan']) + list(bc)))))
    return out


def main():
    ap = argparse.ArgumentParser(description='联合全灭概率 · 历史实测复核')
    ap.add_argument('--period', default='')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()

    from scripts.verify_live_picks import (load_archive, load_ledger,
                                           load_purchased, split_real_paper)
    ledger = load_ledger()
    if not ledger:
        print('  账本为空')
        return 0
    purchased = load_purchased()
    real, paper = split_real_paper(ledger, purchased)
    rows = real or ledger

    periods = sorted({normalize_period(str(r.get('target_period', '')), 'dlt')
                      for r in rows})
    if args.period:
        periods = [normalize_period(args.period, 'dlt')]
    elif not args.all:
        periods = periods[-1:]

    draws = load_draws('dlt')
    if not draws:
        print('  ⚠ 本地库没有大乐透开奖数据')
        return 1
    print(f'  本地库 {len(draws)} 期大乐透开奖数据')

    archive = load_archive()
    for period in periods:
        prows = [r for r in rows
                 if normalize_period(str(r.get('target_period', '')), 'dlt')
                 == period]
        plans = {}
        for r in prows:
            for a in archive:
                if (normalize_period(str(a.get('target_period', '')), 'dlt')
                        == period
                        and str(a.get('ts', '')) == str(r.get('ts', ''))
                        and (a.get('label') or '') == (r.get('label') or '')):
                    plans[r.get('label') or '(未标注)'] = {
                        'front_dan': a.get('front_dan') or [],
                        'front_tuo': a.get('front_tuo') or [],
                        'back_dan': a.get('back_dan') or [],
                        'back_tuo': a.get('back_tuo') or [],
                    }
                    break
        if not plans:
            continue

        tk = {n: expand(p) for n, p in plans.items()}
        per_miss = {n: 0 for n in plans}
        joint = 0
        for _p, _d, f, b in draws:
            fs, bs = set(f), set(b)
            miss = {}
            for n, tl in tk.items():
                hit = False
                for fr, bk in tl:
                    if win_cond(len(fs & set(fr)), len(bs & set(bk))):
                        hit = True
                        break
                miss[n] = not hit
            for n in plans:
                if miss[n]:
                    per_miss[n] += 1
            if all(miss.values()):
                joint += 1

        n = len(draws)
        print()
        print('=' * 74)
        print(f'  联合全灭概率 · 历史实测复核 · 期号 {period}')
        print('=' * 74)
        print(f'  样本: 本地库 {n} 期真实开奖\n')
        for name in plans:
            print(f'    {name:<22} 全灭 {per_miss[name]:>5,} 期 '
                  f'= {per_miss[name] / n * 100:6.2f}%')
        print(f'    {"★ 三套同时全灭":<20} {joint:>7,} 期 '
              f'= {joint / n * 100:6.2f}%')
        print()
        print('  → 与 scripts/joint_miss_prob.py 的全枚举结果对比: '
              '吻合则双方都对')
        print()

        # 本期在历史里的位置
        for p, d, f, b in draws:
            if p == period:
                print(f'  本期 {period} 的开奖: 前区 '
                      f'{" ".join(f"{v:02d}" for v in f)} + 后区 '
                      f'{" ".join(f"{v:02d}" for v in b)}')
                break
        print()

    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
