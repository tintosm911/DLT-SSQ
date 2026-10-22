"""
预测玩法实验室 (CLI)
=====================
用严格 walk-forward 回测检验各种选号策略是否有效。

用法:
  python scripts/strategy_lab.py
  python scripts/strategy_lab.py --game ssq --window 200 --start 500 --seeds 20
  python scripts/strategy_lab.py --game dlt --start 1000 --compare
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.strategy_lab import (run_lab, STRATEGY_DESCRIPTIONS,
                              compute_payout_breakdown)

SEP = '=' * 78


def main():
    ap = argparse.ArgumentParser(description='预测玩法实验室')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--window', type=int, default=200, help='训练窗口 (默认 200 期)')
    ap.add_argument('--start', type=int, default=500, help='从第几期开始回测 (默认 500)')
    ap.add_argument('--seeds', type=int, default=10, help='随机基线种子数 (默认 10)')
    ap.add_argument('--strategies', default='', help='逗号分隔的策略 code (默认全部)')
    ap.add_argument('--compare', action='store_true', help='显示各奖级命中次数对比')
    args = ap.parse_args()

    strategies = ([s.strip() for s in args.strategies.split(',') if s.strip()]
                  or None)

    r = run_lab(args.game, window=args.window, start=args.start,
                n_seeds=args.seeds, strategies=strategies)

    bd = r['payout_breakdown']
    be = r['breakeven']
    b = r['baseline']

    print()
    print(SEP)
    print(f'  预测玩法实验室  —  {r["game_name"]} ({args.game.upper()})')
    print(SEP)
    print(f'  全量 {r["total_draws"]} 期, 回测 {r["tested_draws"]} 期 '
          f'(训练窗口 {r["window"]} 期, 从第 {r["start"]} 期开始逐期重训)')
    print(f'  严格 walk-forward: 每期只用当期之前的数据选号, 绝不使用未来信息')

    print()
    print('  【1】派奖率拆解 (理解一切的钥匙)')
    print(f'      总派奖率:     {bd["total_payout"]:.2f}%  → 理论 ROI {bd["roi_all"]:+.2f}%')
    first = next((d for d in bd['detail'] if d['label'].startswith('一等奖')), None)
    first_odds = (f'1/{int(1 / first["prob"]):,}' if first else '?')
    print(f'      大奖贡献:     {bd["big_payout"]:.2f}%  '
          f'(一等奖 {first_odds}, 二等奖 30 万)')
    print(f'      小奖贡献:     {bd["small_payout"]:.2f}%')
    print(f'      → 剔除大奖后的期望 ROI: {bd["roi_small_only"]:+.2f}%')
    print(f'      (即: 实际能拿到手的只有小奖, 所以 ROI 必然在这个水平附近)')

    print()
    print('  【2】中奖率要多少才不亏')
    print(f'      若中奖全是最低奖级 ({be["lowest_prize_label"]} {be["lowest_prize"]} 元), '
          f'中奖率需 > {be["breakeven_at_lowest"]}%')
    if be.get('best_strategy'):
        print(f'      本次回测最好中奖率: {be["best_strategy"]} {be["best_win_rate"]}%'
              f'  → 差 {be["gap_factor"]:.1f} 倍')
    print(f'      (现实中奖率 6-8%, 与盈亏平衡差一个数量级)')

    print()
    print('  【3】各策略回测结果')
    print(f'      {"策略":<18}{"说明":<26}{"中奖率%":>9}{"ROI%":>9}'
          f'{"净收益":>11}{"最大回撤":>10}')
    print('      ' + '-' * 74)
    for s in sorted(r['strategies'], key=lambda x: -x['roi']):
        desc = s['desc'][:24]
        print(f'      {s["name"]:<18}{desc:<26}{s["win_rate"]:>9.2f}'
              f'{s["roi"]:>9.2f}{s["net"]:>11,.0f}{s["max_drawdown"]:>10,.0f}')

    print()
    print('  【4】随机基线 (对照组)')
    if b.get('count'):
        print(f'      {b["count"]} 个种子: ROI 均值 {b["roi_mean"]:+.2f}%  '
              f'σ {b["roi_std"]:.2f}%')
        print(f'                   最好 {b["roi_max"]:+.2f}%  '
              f'最差 {b["roi_min"]:+.2f}%')
        print(f'      中奖率均值 {b["win_rate_mean"]:.2f}%  '
              f'σ {b["win_rate_std"]:.2f}%')
        print(f'      (单条随机曲线方差极大, 必须看分布)')

    if args.compare:
        print()
        print('  【5】各奖级命中次数对比 (策略有效在哪)')
        names = [s['name'] for s in
                 sorted(r['strategies'], key=lambda x: -x['win_rate'])[:5]]
        d = {s['name']: dict(s['prizes']) for s in r['strategies']}
        labels = sorted({l for n in names for l in d[n]},
                        key=lambda l: -sum(d[n].get(l, 0) for n in names))
        print('      ' + f'{"奖级":<10}' + ''.join(f'{n:>14}' for n in names))
        print('      ' + '-' * (10 + 14 * len(names)))
        for l in labels:
            print('      ' + f'{l:<10}' +
                  ''.join(f'{d[n].get(l, 0):>14}' for n in names))
        print('      ' + '-' * (10 + 14 * len(names)))
        for key, fmt in (('win_rate', '{:>14.2f}'), ('roi', '{:>14.2f}')):
            vals = []
            for n in names:
                s = next(x for x in r['strategies'] if x['name'] == n)
                vals.append(fmt.format(s[key]))
            print('      ' + f'{key:<10}' + ''.join(vals))

    print()
    print('  【结论】')
    for line in r['conclusion'].split(' | '):
        print(f'      • {line}')
    print()
    print(SEP)
    print(f'  理论派奖率 {bd["total_payout"]:.1f}% | 凯利 f* = {r["kelly"]:.3f} '
          f'| 最优策略 ROI 仍然是负数')
    print(SEP)
    print()


if __name__ == '__main__':
    main()
