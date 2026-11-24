"""
生成多组可买的胆拖方案 (多预算 × 多目标)
========================================
用优化器在**多个预算档**和**多个目标**下各求一个最优结构,
输出可直接照买的具体号码, 并诚实标注期望值。

用法:
  python scripts/dan_tuo_plan.py --front-pool "2 4 6 10 14 16 18 23 26 32 35" \
                                 --back-pool "2 4 6 9 12"
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

from data.dan_tuo_optimizer import optimize
from data.games import get_game

GOAL_LABEL = {
    'win': ('最大中奖率', '中奖率最高'),
    'big': ('最大中大奖概率', '≥门槛概率最高'),
    'value': ('最大性价比', '每元钱换到的中奖率最高'),
    'jackpot': ('最大一等奖概率', '头奖概率最高'),
}


def fmt_nums(xs):
    return ' '.join(f'{x:02d}' for x in xs) if xs else '(无)'


def main():
    ap = argparse.ArgumentParser(description='生成多组胆拖方案')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-pool', default='2 4 6 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-pool', default='2 4 6 9 12')
    ap.add_argument('--budgets', default='168,500,1680,5000')
    ap.add_argument('--big-threshold', type=float, default=3000)
    args = ap.parse_args()

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split())

    fp_raw, bp_raw = nums(args.front_pool), nums(args.back_pool)
    cfg = get_game(args.game)
    # ★ 越界号码直接剔除并提示 (两个彩种号码范围不同, 池子常被混用)
    fp = [v for v in fp_raw if 1 <= v <= cfg.front_range]
    bp = [v for v in bp_raw if 1 <= v <= cfg.back_range]
    dropped_f = [v for v in fp_raw if v not in fp]
    dropped_b = [v for v in bp_raw if v not in bp]
    budgets = [int(x) for x in args.budgets.split(',') if x.strip()]

    print()
    print('=' * 96)
    print(f'  胆拖方案生成 — {cfg.name}')
    print('=' * 96)
    print(f'  前区号码池 ({len(fp)} 个): {fmt_nums(fp)}')
    print(f'  后区号码池 ({len(bp)} 个): {fmt_nums(bp)}')
    if dropped_f or dropped_b:
        print(f'  ⚠ 已剔除越界号码: 前区 {dropped_f or "无"} / 后区 {dropped_b or "无"}'
              f'  ({cfg.name} 前区 1-{cfg.front_range} / 后区 1-{cfg.back_range})')
        print(f'    —— 越界号在开奖里永远不出现, 算进去只会虚增注数、'
              f'并把中奖率算高 (是错的数字)')
    print()
    print(f'  {"":4}{"预算":>8}{"目标":<14}{"结构":<26}{"注数":>7}'
          f'{"中奖率":>9}{"期望净收益":>12}')
    print('  ' + '-' * 80)

    plans = []
    for b in budgets:
        for goal in ('win', 'big'):
            r = optimize(args.game, budget=b, goal=goal,
                         big_threshold=args.big_threshold,
                         front_pool=fp, back_pool=bp, top_n=1)
            if not r['best']:
                continue
            best = r['best']
            plans.append((b, goal, best))
            print(f'  {len(plans):<4}{b:>7}元{GOAL_LABEL[goal][0]:<14}'
                  f'{best["structure"]:<26}{best["n_bets"]:>7,}'
                  f'{best["win_rate"]:>8.2f}%{best["expected_net"]:>+12,.0f}')

    print('  ' + '-' * 80)
    print()

    # 详细输出
    for i, (b, goal, best) in enumerate(plans, 1):
        print(f'  ── 方案 {i} · 预算 {b:,} 元 · {GOAL_LABEL[goal][0]} ──')
        print(f'    {best["structure"]}')
        print(f'    注数 {best["n_bets"]:,} 注 · 花费 {best["cost"]:,.0f} 元')
        print(f'    中奖率 {best["win_rate"]:.4f}%   '
              f'≥{args.big_threshold:,.0f}元 概率 {best["big_prob"]:.4f}%')
        print(f'    期望返奖 {best["expected_return"]:,.2f} 元   '
              f'期望净收益 {best["expected_net"]:+,.2f} 元 '
              f'({best["expected_net"] / best["n_bets"]:+.4f} 元/注)')
        print(f'    前区  胆 {fmt_nums(best["front_dan"])}   '
              f'拖 {fmt_nums(best["front_tuo"])}')
        print(f'    后区  胆 {fmt_nums(best["back_dan"])}   '
              f'拖 {fmt_nums(best["back_tuo"])}')
        top = sorted(best['prize_prob'].items(), key=lambda x: -x[1])[:4]
        print(f'    主要奖级: ' + ', '.join(
            f'{k} {v:.2f}%' for k, v in top))
        print()

    print('  ' + '=' * 92)
    print('  【诚实声明 — 每一组都必亏】')
    print('  ' + '=' * 92)
    print(f'    · 所有方案的单注期望净收益都是 '
          f'{-0.9407 if args.game == "dlt" else -0.8570:.4f} 元/注，'
          f'**没有任何一组例外**。')
    print('    · 上面"最优"的意思只是：**同样的钱更容易中一次小奖**。')
    print('    · 中奖率最高的那组，也不是"更赚钱"——花得更多，亏得一样快。')
    print('    · 号码选哪几个，在概率上**完全等价**（只取决于胆码个数与拖码池大小）。')
    print()


if __name__ == '__main__':
    main()
