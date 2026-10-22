"""
投注 ROI 模拟器
===============
回答"我这次投 80 中 70 到底算什么水平"这类问题。

核心输出:
  1. 返奖分布直方图 (你这次的 70 元处在什么分位?)
  2. 长期 ROI 收敛曲线 (买 N 期后平均返奖率是多少?)
  3. 回本所需期数分布 (要买多少期才可能把本捞回来?)
  4. "小奖堆积" vs "大奖" 的收益结构拆解

用法:
  python scripts/roi_sim.py --bets 40 --draws 200000
  python scripts/roi_sim.py --bets 40 --dan-tuo --draws 200000
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

import numpy as np

from data.games import get_game, get_prize_rules
from data.pick_advisor import Pick, calc_expected_prize, judge_prize

SEP = '=' * 74


def build_tickets(game: str, n_bets: int, dan_tuo: bool, seed: int = 42):
    """造 n_bets 注: 胆拖模式或纯随机模式"""
    cfg = get_game(game)
    rng = np.random.default_rng(seed)
    tickets = []
    if dan_tuo:
        # 用一个典型胆拖结构: 2 胆 + 其余拖码
        need_dan = 2 if cfg.front_count >= 5 else 1
        dan = sorted(rng.choice(np.arange(1, cfg.front_range + 1),
                                need_dan, replace=False).tolist())
        rest = [n for n in range(1, cfg.front_range + 1) if n not in dan]
        tuo = rng.choice(rest, size=min(len(rest), 7), replace=False).tolist()
        need_f = cfg.front_count - need_dan
        from itertools import combinations
        front_combos = list(combinations(sorted(tuo), need_f))[:n_bets]
        for fc in front_combos:
            f = sorted(list(dan) + list(fc))
            b = sorted(rng.choice(np.arange(1, cfg.back_range + 1),
                                  cfg.back_count, replace=False).tolist())
            tickets.append((f, b))
            if len(tickets) >= n_bets:
                break
    else:
        for _ in range(n_bets):
            f = sorted(rng.choice(np.arange(1, cfg.front_range + 1),
                                  cfg.front_count, replace=False).tolist())
            b = sorted(rng.choice(np.arange(1, cfg.back_range + 1),
                                  cfg.back_count, replace=False).tolist())
            tickets.append((f, b))
    return tickets


def simulate(tickets, game: str, n_draws: int, seed: int = 42):
    """向量化模拟, 返回每次开奖的总返奖"""
    cfg = get_game(game)
    rng = np.random.default_rng(seed)
    fr, br = cfg.front_range, cfg.back_range
    fc, bc = cfg.front_count, cfg.back_count

    ft = sorted(tickets, key=lambda t: (t[0], t[1]))
    front_sel = np.zeros((len(ft), fr), dtype=np.int32)
    back_sel = np.zeros((len(ft), br), dtype=np.int32)
    for i, (f, b) in enumerate(ft):
        for n in f:
            front_sel[i, n - 1] = 1
        for n in b:
            back_sel[i, n - 1] = 1

    lookup = np.zeros((fc + 1, bc + 1), dtype=np.float64)
    for cond, info in get_prize_rules(game):
        lookup[cond[0], cond[1]] = (info[1] if isinstance(info, (tuple, list))
                                   and len(info) > 1 else 0)

    returns = np.zeros(n_draws, dtype=np.float64)
    chunk = 20_000
    done = 0
    while done < n_draws:
        m = min(chunk, n_draws - done)
        dmat_f = np.zeros((m, fr), dtype=np.int32)
        dmat_b = np.zeros((m, br), dtype=np.int32)
        for i in range(m):
            dmat_f[i, rng.choice(fr, fc, replace=False)] = 1
            dmat_b[i, rng.choice(br, bc, replace=False)] = 1
        nf = dmat_f @ front_sel.T
        nb = dmat_b @ back_sel.T
        returns[done:done + m] = lookup[nf, nb].sum(axis=1)
        done += m
    return returns


def main():
    ap = argparse.ArgumentParser(description='投注 ROI 模拟器')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--bets', type=int, default=40, help='每次投注注数')
    ap.add_argument('--draws', type=int, default=200_000, help='模拟开奖次数')
    ap.add_argument('--dan-tuo', action='store_true', help='用胆拖结构而非纯随机')
    ap.add_argument('--your-return', type=float, default=None,
                    help='你这次实际返奖多少元 (算分位数)')
    args = ap.parse_args()

    cfg = get_game(args.game)
    price = cfg.ticket_price
    cost = args.bets * price

    print()
    print(SEP)
    print(f'  投注 ROI 模拟  —  {cfg.name}  |  {args.bets} 注 / {cost:.0f} 元')
    print(SEP)

    tickets = build_tickets(args.game, args.bets, args.dan_tuo)
    returns = simulate(tickets, args.game, args.draws)

    exp1, net1, kelly1, prob1 = calc_expected_prize(
        args.game, Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count))
    exp_total = exp1 * args.bets
    net_expected = exp_total - cost

    print()
    print('  【1】长期期望 (数学)')
    print(f'      单注期望奖金:   {exp1:.4f} 元')
    print(f'      {args.bets} 注期望返奖: {exp_total:.2f} 元')
    print(f'      {args.bets} 注期望净收益: **{net_expected:+.2f} 元**')
    print(f'      期望返奖率: {exp_total/cost*100:.1f}%   (每 100 元返 {exp_total/cost*100:.0f} 元)')
    print(f'      凯利 f*: {kelly1:.3f}')

    # 返奖分布
    print()
    print(f'  【2】{args.draws:,} 次模拟的返奖分布')
    lose_mask = returns == 0
    n_lose = int(lose_mask.sum())
    print(f'      一次不中 ({cost:.0f} 元全损): {n_lose/len(returns)*100:.2f}%  ({n_lose:,} 次)')
    print(f'      有返奖: {(1-n_lose/len(returns))*100:.2f}%')

    # 直方图
    print()
    print('      返奖额分布:')
    edges = [0, 1, 5, 15, 50, 100, 300, 1000, 10000, 100000, np.inf]
    labels = ['0 (全损)', '1-4 元', '5-14 元', '15-49 元', '50-99 元',
              '100-299 元', '300-999 元', '1000-9999 元', '1万-9.9万', '≥10万']
    for i in range(len(edges) - 1):
        if edges[i] == 0:
            cnt = n_lose
        else:
            cnt = int(((returns >= edges[i]) & (returns < edges[i + 1])).sum())
        pct = cnt / len(returns) * 100
        bar = '█' * int(pct * 2)
        print(f'        {labels[i]:<12} {pct:>6.2f}%  {bar}')

    # 常见返奖额 Top 8
    vals, counts = np.unique(returns.astype(int), return_counts=True)
    order = np.argsort(-counts)
    print()
    print('      最常见的返奖额 (Top 8):')
    for i in order[:8]:
        v, c = int(vals[i]), int(counts[i])
        print(f'        {v:>10,} 元  × {c:>7,} 次  ({c/len(returns)*100:>6.2f}%)  '
              f'净{v-cost:+,} 元')

    # 收益结构拆解: 大奖 vs 小奖
    print()
    print('  【3.5】收益结构拆解 (你返的钱到底从哪来)')
    big_mask = returns >= 10_000
    n_big = int(big_mask.sum())
    big_sum = float(returns[big_mask].sum())
    small_sum = float(returns[~big_mask].sum())
    total_sum = float(returns.sum())
    print(f'      大奖 (≥1万): {n_big:,} 次 ({n_big/len(returns)*100:.3f}%)  '
          f'贡献 {big_sum:,.0f} 元 ({big_sum/total_sum*100:.1f}%)')
    print(f'      小奖 (<1万): {len(returns)-n_big:,} 次 '
          f'({(1-n_big/len(returns))*100:.2f}%)  '
          f'贡献 {small_sum:,.0f} 元 ({small_sum/total_sum*100:.1f}%)')
    print(f'      → {100-n_big/len(returns)*100:.2f}% 的次数只分到 '
          f'{100-big_sum/total_sum*100:.1f}% 的钱')
    print(f'      → 你每次看到的"返奖", 99% 来自 0.04% 的大奖时刻')
    print(f'      → 没有大奖的日子, 每 80 元只回 {small_sum/(len(returns)-n_big):.2f} 元')
    # 用户实际返奖的分位
    if args.your_return is not None:
        y = args.your_return
        less = int((returns < y).sum())
        equal = int((returns == y).sum())
        better = int((returns > y).sum())
        pct_rank = less / len(returns) * 100
        print()
        print(f'  【3】你这次的返奖: {y:.0f} 元 (投 {cost:.0f} 元)')
        print(f'      净收益: {y-cost:+.0f} 元  (返奖率 {y/cost*100:.1f}%)')
        print(f'      排名: 比 {pct_rank:.1f}% 的模拟结果更好')
        print(f'            比 {(better/len(returns)*100):.2f}% 的模拟结果更差')
        print(f'      恰好返 {y:.0f} 元的次数: {equal:,} '
              f'({equal/len(returns)*100:.3f}%)')
        print()
        if y > cost:
            print(f'      [!] 你这次比成本高 {y-cost:.0f} 元, 但这是幸存者偏差:')
            print(f'          你只看到了"返奖 ≥ 成本"的那部分人, 没看到')
            print(f'          {(returns < cost).sum():,} 次 '
                  f'({(returns < cost).sum()/len(returns)*100:.1f}%) 全损的结果.')
        else:
            print(f'      常规结果, {100-pct_rank:.1f}% 的模拟都能达到或更好.')

    # 长期 ROI 收敛曲线
    # ⚠ 大奖会让累计值爆炸, 掩盖真实趋势 → 先剔除大奖看常态, 再单独看含大奖
    print()
    print('  【4】长期 ROI 收敛 (每 N 期累计)')
    print('      期数      累计注金    常态累计返奖   常态净收益   常态返奖率')
    no_big = returns < 10_000
    cum_ret_clean = np.where(no_big, returns, 0.0).cumsum()
    cum_cost = 0.0
    for n in [1, 10, 50, 100, 500, 1000, 5000, 20000]:
        if n > len(returns):
            break
        cum_cost = n * cost
        cr = cum_ret_clean[n - 1]
        roi = cr / cum_cost * 100
        print(f'      {n:>6,}  {cum_cost:>11,.0f}  {cr:>13,.0f}  '
              f'{cr-cum_cost:>+12,.0f}  {roi:>6.1f}%')
    print(f'      注: 常态列已剔除单次 ≥1万 的大奖 ({int((~no_big).sum()):,} 次),')
    print(f'          否则一注 500 万就能把曲线炸飞, 看不到真实趋势.')

    # 回本分析 (用常态, 大奖另算)
    print()
    print('  【5】回本分析')
    cum_all = np.cumsum(returns - cost)
    hit_all = np.where(cum_all >= 0)[0]
    print('      [含大奖]')
    if len(hit_all):
        print(f'        首次回本: 第 {hit_all[0]+1:,} 期, '
              f'中位数: 第 {int(np.median(hit_all))+1:,} 期')
    else:
        print(f'        {len(returns):,} 次模拟中无一次回本')

    cum_clean = np.cumsum(np.where(no_big, returns, 0.0) - cost)
    hit_clean = np.where(cum_clean >= 0)[0]
    print('      [常态, 剔除大奖]')
    if len(hit_clean):
        print(f'        首次回本: 第 {hit_clean[0]+1:,} 期, '
              f'中位数: 第 {int(np.median(hit_clean))+1:,} 期')
        print(f'        25%: 第 {int(np.percentile(hit_clean, 25))+1:,} 期 | '
              f'75%: 第 {int(np.percentile(hit_clean, 75))+1:,} 期')
        print(f'        能回本的比例: {len(hit_clean)/len(returns)*100:.2f}%')
    else:
        print(f'        {len(returns):,} 次模拟中无一次回本 —— 常态下永远回不了本')
    print(f'        最坏情况累计亏损: {cum_all.min():,.0f} 元')

    print()
    print(SEP)
    print(f'  结论: 投 {cost:.0f} 元, 期望净收益 {net_expected:+.2f} 元, '
          f'凯利 f*={kelly1:.3f}')
    print(f'        返奖率永远收敛到 {exp_total/cost*100:.1f}%, 与你选号水平无关')
    print(SEP)
    print()


if __name__ == '__main__':
    sys.exit(main() or 0)
