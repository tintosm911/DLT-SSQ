"""
胆拖结构优化器 (CLI)
=====================
给定预算和目标, 自动搜出最优的胆拖结构 + 具体号码。

用法:
  # 1680 元, 最大化中奖率, 号码池用你给的那 11+5 个
  python scripts/dan_tuo_optimizer.py --budget 1680 --goal win \
      --front-pool "2 4 6 10 14 16 18 23 26 32 35" --back-pool "2 4 6 9 12"

  # 500 元, 最大化中大奖概率 (四等奖及以上)
  python scripts/dan_tuo_optimizer.py --budget 500 --goal big

  # 1000 元, 最大化性价比 (每元钱换到的中奖率)
  python scripts/dan_tuo_optimizer.py --budget 1000 --goal value

  # 不限号码池 (相当于复式), 5000 元
  python scripts/dan_tuo_optimizer.py --budget 5000 --goal win --pool-size-f 35 --pool-size-b 12

★ 所有数字都用**精确超几何**算 (data/dan_tuo_exact.py), 不是模拟。
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

from data.dan_tuo_optimizer import GOALS, optimize
from data.games import get_game


def main():
    ap = argparse.ArgumentParser(description='胆拖结构优化器')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--budget', type=float, default=100.0, help='预算 (元)')
    ap.add_argument('--goal', default='win', choices=list(GOALS),
                    help='优化目标')
    ap.add_argument('--big-threshold', type=float, default=None,
                    help='big 目标下的大奖门槛 (元, 默认 3000)')
    ap.add_argument('--front-pool', default='', help='前区候选号码池 (空格分隔)')
    ap.add_argument('--back-pool', default='', help='后区候选号码池')
    ap.add_argument('--pool-size-f', type=int, default=None,
                    help='不给号码池时, 搜索这个大小的池 (默认全池)')
    ap.add_argument('--pool-size-b', type=int, default=None)
    ap.add_argument('--fill', default='hot', choices=['hot', 'cold', 'random'],
                    help='填号码策略 (对概率无影响)')
    ap.add_argument('--top', type=int, default=8, help='展示前 N 个候选')
    ap.add_argument('--max-cost', type=float, default=None,
                    help='实际花费上限 (默认等于预算)')
    args = ap.parse_args()

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split()) if s.strip() else None

    fp, bp = nums(args.front_pool), nums(args.back_pool)
    cfg = get_game(args.game)

    r = optimize(args.game, budget=args.budget, goal=args.goal,
                 big_threshold=args.big_threshold,
                 front_pool=fp, back_pool=bp,
                 pool_size_f=args.pool_size_f, pool_size_b=args.pool_size_b,
                 fill=args.fill, top_n=args.top, max_cost=args.max_cost)

    print()
    print('=' * 92)
    print(f'  胆拖结构优化器 — {cfg.name}')
    print('=' * 92)
    print(f'  预算 {r["budget"]:,.0f} 元 · 目标: {r["goal_cn"]} ({r["goal_desc"]})')
    if args.goal == 'big':
        print(f'  大奖门槛: {r["threshold"]:,.0f} 元')
    print(f'  前区号码池: {fp if fp else "不限 (全 35 号)"}')
    print(f'  后区号码池: {bp if bp else "不限 (全 12 号)"}')
    print(f'  已搜索 {r["searched"]:,} 种结构')
    print()

    if not r['best']:
        print(f'  ⚠ {r.get("note", "无解")}')
        return

    b = r['best']
    print('  ┌─ ★ 最优方案 ─────────────────────────────────────────────────')
    print(f'  │ 结构        : {b["structure"]}')
    print(f'  │ 注数 / 花费 : {b["n_bets"]:,} 注 / {b["cost"]:,.0f} 元')
    print(f'  │ 中奖率      : {b["win_rate"]:.4f}%')
    print(f'  │ 期望返奖    : {b["expected_return"]:,.2f} 元'
          f'   期望净收益: {b["expected_net"]:+,.2f} 元 (ROI {b["roi"]*100:+.2f}%)')
    print(f'  │ 前区 胆 {" ".join(f"{v:02d}" for v in b["front_dan"]) or "(无)"}'
          f'   拖 {" ".join(f"{v:02d}" for v in b["front_tuo"])}')
    print(f'  │ 后区 胆 {" ".join(f"{v:02d}" for v in b["back_dan"]) or "(无)"}'
          f'   拖 {" ".join(f"{v:02d}" for v in b["back_tuo"])}')
    print('  └──────────────────────────────────────────────────────────────')
    print()

    print(f'  奖级命中概率 (至少中一注):')
    money_map = {}
    from data.games import get_prize_rules
    for cond, info in get_prize_rules(args.game):
        money_map[info[0]] = float(info[1]) if len(info) > 1 else 0.0
    for lab, p in sorted(b['prize_prob'].items(),
                          key=lambda x: -money_map.get(x[0], 0.0)):
        mv = money_map.get(lab, 0.0)
        bar = '█' * int(p / 2)
        print(f'    {lab:<8}{mv:>12,.0f} 元  {p:>9.4f}%  {bar}')
    print()

    print(f'  前 {args.top} 个候选:')
    print(f'  {"结构":<28}{"注数":>9}{"花费":>9}{"中奖率":>10}'
          f'{">=门槛":>11}{"期望净收益":>12}')
    print('  ' + '-' * 79)
    for c in r['candidates']:
        print(f'  {c["structure"]:<28}{c["n_bets"]:>9,}{c["cost"]:>9,.0f}'
              f'{c["win_rate"]:>9.2f}%{c["big_prob"]:>10.4f}%'
              f'{c["expected_net"]:>+12,.0f}')
    print('  ' + '-' * 79)
    print()
    print(f'  说明: {r["note"]}')
    print()


def _money(label: str, game: str) -> float:
    from data.games import get_prize_rules
    for cond, info in get_prize_rules(game):
        if info[0] == label:
            return float(info[1]) if len(info) > 1 else 0.0
    return 0.0


if __name__ == '__main__':
    main()