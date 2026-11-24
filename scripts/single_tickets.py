"""
单式号码生成器 —— 从号码池里出一组**普通单式**号码
====================================================
胆拖之外最常用的玩法: 每注 5 前区 + 2 后区 (大乐透) / 6 红 + 1 蓝 (双色球)。

用法:
  # 大乐透 10 注 (热号优先)
  python scripts/single_tickets.py --game dlt --n 10 \
      --pool-f "2 3 4 6 10 11 12 22 23 26 27 32" --pool-b "2 4 5 6 7 8 9 10 12"

  # 双色球 5 注, 号码尽量分散 (每注覆盖不同的号)
  python scripts/single_tickets.py --game ssq --n 5 --mode spread \
      --pool-f "30 4 14 13 22 26 5 10 20 6" --pool-b "11 12 4 14 2"

  # 出清单 + 跑真实历史回测 (慢: 每注要跑满全部期数)
  python scripts/single_tickets.py --game dlt --n 10 --backtest \
      --out reports/大乐透_10组单式.txt

★ 三种填号模式:
  hot    —— 优先用池子前部 (你按热度排的顺序), 前面的号进每注
  spread —— 每注覆盖尽量不同的号码 (最大化组合多样性)
  random —— 随机

★ 诚实提示 (每次输出都会带):
  · 单注中奖率对**所有号码完全相同** (组合数学恒等式), 冷热不影响概率
  · 每注期望净收益恒为负 (大乐透 -0.9407 元 / 双色球 -0.8570 元)
  · 注数越多中奖率越高, 但常态 ROI 恒在 -73% 左右
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from math import comb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import get_game, get_prize_rules


def _nums(s: str) -> list:
    out = []
    for x in s.replace(',', ' ').split():
        v = int(x)
        if v not in out:
            out.append(v)
    return out


def _single_win_prob(game: str) -> float:
    """单注中奖概率 (任意奖级) —— 与号码无关, 只由彩种决定"""
    cfg = get_game(game)
    lut = {(int(c[0]), int(c[1])): float(i[1])
           for c, i in get_prize_rules(game)}
    cnt = 0
    for nf in range(cfg.front_count + 1):
        for nb in range(cfg.back_count + 1):
            if lut.get((nf, nb), 0) > 0:
                cnt += (comb(cfg.front_count, nf)
                        * comb(cfg.front_range - cfg.front_count,
                               cfg.front_count - nf)
                        * comb(cfg.back_count, nb)
                        * comb(cfg.back_range - cfg.back_count,
                               cfg.back_count - nb))
    total = (comb(cfg.front_range, cfg.front_count)
             * comb(cfg.back_range, cfg.back_count))
    return cnt / total


def _single_expected_return(game: str) -> float:
    """单注期望返奖 (浮动奖取保底金额, 保守口径)"""
    cfg = get_game(game)
    lut = {(int(c[0]), int(c[1])): float(i[1])
           for c, i in get_prize_rules(game)}
    total = (comb(cfg.front_range, cfg.front_count)
             * comb(cfg.back_range, cfg.back_count))
    acc = 0.0
    for nf in range(cfg.front_count + 1):
        for nb in range(cfg.back_count + 1):
            m = lut.get((nf, nb), 0)
            if m <= 0:
                continue
            ways = (comb(cfg.front_count, nf)
                    * comb(cfg.front_range - cfg.front_count,
                           cfg.front_count - nf)
                    * comb(cfg.back_count, nb)
                    * comb(cfg.back_range - cfg.back_count,
                           cfg.back_count - nb))
            acc += ways / total * m
    return acc


def _combos_in_order(pool, k):
    """按**池子给定顺序**生成组合 (前面的号优先) —— 不是数字升序"""
    return [[pool[i] for i in idx]
            for idx in itertools.combinations(range(len(pool)), k)]


def _all_combos(pool_f, pool_b, cfg):
    fronts = _combos_in_order(pool_f, cfg.front_count)
    backs = _combos_in_order(pool_b, cfg.back_count)
    return fronts, backs


def _gen(pool_f, pool_b, cfg, n, mode, seed=20261124):
    """生成 n 注互不相同的单式"""
    fronts, backs = _all_combos(pool_f, pool_b, cfg)
    if not fronts or not backs:
        raise SystemExit('❌ 号码池太小, 凑不出单式')
    rng = random.Random(seed)
    out, seen = [], set()

    if mode == 'hot':
        # ★ 前区组合按池子顺序取 (靠前的号优先), 后区独立轮换
        #   → 每注的**前区都不同**, 否则 10 注会挤在同一个组合上 (中奖率掉一半)
        for i, f in enumerate(fronts):
            b = backs[i % len(backs)]
            k = (tuple(f), tuple(b))
            if k in seen:
                continue
            seen.add(k)
            out.append((f, b))
            if len(out) >= n:
                break
    elif mode == 'spread':
        # ★ 贪心: 每注挑"累计用得最少"的号 → 各注覆盖尽量不同的组合
        use_f = {v: 0 for v in pool_f}
        use_b = {v: 0 for v in pool_b}
        while len(out) < n:
            best = None
            best_score = None
            for f in fronts:
                for b in backs:
                    k = (tuple(f), tuple(b))
                    if k in seen:
                        continue
                    sc = (sum(use_f[v] for v in f) + sum(use_b[v] for v in b))
                    if best_score is None or sc < best_score:
                        best_score = sc
                        best = (f, b)
            if best is None:
                break
            f, b = best
            seen.add((tuple(f), tuple(b)))
            out.append((f, b))
            for v in f:
                use_f[v] += 1
            for v in b:
                use_b[v] += 1
    else:  # random
        while len(out) < n:
            f = rng.choice(fronts)
            b = rng.choice(backs)
            k = (tuple(f), tuple(b))
            if k in seen:
                continue
            seen.add(k)
            out.append((f, b))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='单式号码生成器')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--n', type=int, default=10, help='生成几注')
    ap.add_argument('--pool-f', default='', help='前区号码池 (逗号或空格分隔)')
    ap.add_argument('--pool-b', default='', help='后区号码池')
    ap.add_argument('--mode', default='hot', choices=['hot', 'spread', 'random'])
    ap.add_argument('--out', default='', help='输出清单文件')
    ap.add_argument('--backtest', action='store_true', help='跑真实历史回测 (慢)')
    args = ap.parse_args()

    cfg = get_game(args.game)
    pool_f = _nums(args.pool_f) if args.pool_f else list(
        range(1, cfg.front_range + 1))
    pool_b = _nums(args.pool_b) if args.pool_b else list(
        range(1, cfg.back_range + 1))

    # 范围校验
    bad_f = [v for v in pool_f if not (1 <= v <= cfg.front_range)]
    bad_b = [v for v in pool_b if not (1 <= v <= cfg.back_range)]
    if bad_f or bad_b:
        raise SystemExit(f'❌ 号码越界: 前区 {bad_f} / 后区 {bad_b} '
                         f'({cfg.name} 前区 1-{cfg.front_range} '
                         f'后区 1-{cfg.back_range})')
    if len(pool_f) < cfg.front_count or len(pool_b) < cfg.back_count:
        raise SystemExit(f'❌ 号码池不够 ({cfg.name} 需要前区 '
                         f'{cfg.front_count} 个 / 后区 {cfg.back_count} 个)')

    tickets = _gen(pool_f, pool_b, cfg, args.n, args.mode)
    if len(tickets) < args.n:
        raise SystemExit(f'❌ 号码池最多只能凑出 {len(tickets)} 注不重复的单式')

    p1 = _single_win_prob(args.game)
    e1 = _single_expected_return(args.game)
    total_cost = len(tickets) * cfg.ticket_price

    print()
    print('=' * 84)
    print(f'  {cfg.name} 单式号码 {len(tickets)} 注 — 模式 {args.mode}')
    print('=' * 84)
    print(f'  {"":4}{cfg.front_label:<12}{cfg.back_label}     和值  奇偶')
    for i, (f, b) in enumerate(tickets, 1):
        odd = sum(1 for v in f if v % 2)
        print(f'  {i:>3})  ' + ' '.join(f'{v:02d}' for v in f)
              + '  +  ' + ' '.join(f'{v:02d}' for v in b)
              + f'   {sum(f):>4}  {odd}:{len(f) - odd}')
    print('  ' + '-' * 84)
    print(f'  合计 {len(tickets)} 注 · {total_cost:,.0f} 元')
    print(f'  单注中奖率 {p1 * 100:.4f}%   '
          f'单注期望返奖 {e1:.4f} 元 → 单注期望净收益 {e1 - cfg.ticket_price:+.4f} 元')
    print(f'  {len(tickets)} 注合计期望净收益 '
          f'{len(tickets) * (e1 - cfg.ticket_price):+.2f} 元')
    print()

    if args.backtest:
        from data.pick_advisor import Pick, judge_prize
        import sqlite3
        con = sqlite3.connect(str(PROJECT_ROOT / 'data-raw' / 'lottery.db'))
        rows = con.execute(
            'SELECT front_numbers, back_numbers FROM draws '
            'WHERE game=? ORDER BY period', (args.game,)).fetchall()
        levels = {}
        money = 0.0
        per_period = []
        hits = 0
        for fj, bj in rows:
            af, ab = json.loads(fj), json.loads(bj)
            got = False
            rp = 0.0
            for f, b in tickets:
                lab, m = judge_prize(args.game, Pick(front=f, back=b), af, ab)
                if m > 0:
                    levels[lab] = levels.get(lab, 0) + 1
                    money += m
                    rp += m
                    got = True
            per_period.append(rp)
            if got:
                hits += 1
        stake = len(rows) * len(tickets) * cfg.ticket_price
        big = [v for v in per_period if v >= 10000]
        ret_nb = sum(v for v in per_period if v < 10000)
        print(f'  ── 真实历史回测 ({len(rows):,} 期 × {len(tickets)} 注 = '
              f'{len(rows) * len(tickets):,} 次判奖) ──')
        print(f'     中奖率 {hits / len(rows) * 100:.2f}%   '
              f'投入 {stake:,.0f} → 返奖 {money:,.0f} 元')
        print(f'     含大奖 ROI {(money - stake) / stake * 100:+.2f}%   '
              f'常态 ROI {(ret_nb - stake) / stake * 100:+.2f}% '
              f'(剔除 {len(big)} 个大奖期)')
        print('     奖级: ' + ', '.join(f'{k}×{v:,}' for k, v in
                                      sorted(levels.items(), key=lambda x: -x[1])[:6]))
        print()

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [f'{cfg.name} {len(tickets)} 注单式号码', '=' * 60,
                 f'{cfg.front_label}池: {" ".join(f"{v:02d}" for v in pool_f)}',
                 f'{cfg.back_label}池: {" ".join(f"{v:02d}" for v in pool_b)}',
                 '-' * 60]
        for i, (f, b) in enumerate(tickets, 1):
            lines.append(f'{i:>3}) ' + ' '.join(f'{v:02d}' for v in f)
                         + '  +  ' + ' '.join(f'{v:02d}' for v in b))
        lines += ['=' * 60,
                  f'{len(tickets)} 注 / {total_cost:,.0f} 元 · '
                  f'单注中奖率 {p1 * 100:.4f}% · '
                  f'单注期望净收益 {e1 - cfg.ticket_price:+.4f} 元',
                  '★ 单注中奖率对所有号码完全相同 —— 冷热只影响"你押哪几个", '
                  '不影响概率。']
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'  ✅ 清单已写出: {p.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
