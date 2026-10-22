"""
胆拖结构矩阵 (精确)
==================
在**固定号码池**下, 枚举前区/后区胆码数量的所有组合,
精确算出每个结构的注数、花费、中奖率、奖级分布。

★ 核心定理 (组合数学, 非经验):
  在固定号码池下, 胆拖方案的**中奖率只取决于胆码的个数**,
  与"胆码具体选哪几个号"**完全无关**。
  原因: 开奖对所有号码完全对称 —— 把胆码换成拖码里的另一个号,
        只是把注的集合换了一个, 概率分布不变。
  → 所以"追热号"和"追冷号"在概率上等价, 这是数学事实, 不是统计现象。

用法:
  python scripts/dantuo_structure_matrix.py
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from math import comb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.dan_tuo_exact import exact_dan_tuo
from data.games import get_game


def main():
    ap = argparse.ArgumentParser(description='胆拖结构矩阵 (精确)')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-pool', default='2 4 6 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-pool', default='2 4 6 9 12')
    ap.add_argument('--budget', type=float, default=1680.0,
                    help='参考预算(元), 用于标出同预算下的最优结构')
    args = ap.parse_args()

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split())

    fp, bp = nums(args.front_pool), nums(args.back_pool)
    cfg = get_game(args.game)

    rows = []
    for k in range(0, cfg.front_count + 1):
        for m in range(0, cfg.back_count + 1):
            fd = fp[:k]
            ft = fp[k:]
            bd = bp[:m]
            bt = bp[m:]
            if len(ft) < cfg.front_count - k or len(bt) < cfg.back_count - m:
                continue
            r = exact_dan_tuo(args.game, fd, ft, bd, bt)
            r['k'], r['m'] = k, m
            rows.append(r)

    print()
    print('=' * 100)
    print(f'  胆拖结构矩阵 (精确超几何)  —  {cfg.name}')
    print(f'  前区池 {len(fp)} 个: {fp}')
    print(f'  后区池 {len(bp)} 个: {bp}')
    print(f'  ★ 中奖率只取决于胆码**个数**, 与具体选哪几个号无关 (开奖对称性)')
    print('=' * 100)
    print()
    print(f'  {"前胆":>4}{"后胆":>5}{"注数":>9}{"花费":>9}{"期望净收益":>12}'
          f'{"中奖率":>10}{"≥3等奖":>10}{"≥5等奖":>10}{"全灭":>10}')
    print('  ' + '-' * 88)
    for r in rows:
        p3 = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 10000) * 100
        p5 = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 300) * 100
        mark = ' ←' if abs(r['cost'] - args.budget) < 1 else ''
        print(f'  {r["k"]:>4}{r["m"]:>5}{r["n_bets"]:>9,}{r["cost"]:>9,.0f}'
              f'{r["expected_net"]:>+12,.0f}{r["win_rate"]:>9.2f}%'
              f'{p3:>9.3f}%{p5:>9.3f}%{r["lose_rate"]:>9.2f}%{mark}')
    print('  ' + '-' * 88)
    print()

    # --- 同预算最优 ---
    under = [r for r in rows if r['cost'] <= args.budget]
    if under:
        best = max(under, key=lambda x: x['win_rate'])
        print(f'  【预算 ≤ {args.budget:,.0f} 元 的最优结构】')
        print(f'    前区胆 {best["k"]} 个 / 后区胆 {best["m"]} 个'
              f'  →  {best["n_bets"]:,} 注 / {best["cost"]:,.0f} 元')
        print(f'    中奖率 {best["win_rate"]:.2f}%   期望净收益 {best["expected_net"]:+.0f} 元')
        print(f'    建议号码: 前区 胆 {" ".join(f"{v:02d}" for v in fp[:best["k"]]) or "(无)"}'
              f' / 拖 {" ".join(f"{v:02d}" for v in fp[best["k"]:])}')
        print(f'              后区 胆 {" ".join(f"{v:02d}" for v in bp[:best["m"]]) or "(无)"}'
              f' / 拖 {" ".join(f"{v:02d}" for v in bp[best["m"]:])}')
        print()

    # --- 性价比榜: 每 100 元换到的中奖率 ---
    print('  【性价比: 每 100 元买到多少中奖率】')
    ranked = sorted(rows, key=lambda x: -x['win_rate'] / x['cost'] * 100)
    for r in ranked[:6]:
        print(f'    {r["k"]}前胆/{r["m"]}后胆  {r["cost"]:>7,.0f}元  '
              f'中奖率 {r["win_rate"]:>6.2f}%  → 每百元 '
              f'{r["win_rate"] / r["cost"] * 100:>6.3f}%')
    print()
    print('  ⚠ 注意: 这不是"更划算", 只是"花同样的钱更容易中一次小奖"。')
    print('    单注期望净收益永远是同一个负数, 换任何结构都改不了。')
    print()


if __name__ == '__main__':
    main()
