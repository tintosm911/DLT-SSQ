"""
胆拖方案对比生成器 (精确版)
============================
给定用户的号码池, 生成几组**结构不同**的胆拖方案, 横向对比:
  注数 / 花费 / 精确期望返奖 / 精确中奖率 / 各奖级命中概率 / 覆盖组合数

★ 核心诚实点: 所有方案的**单注期望净收益完全相同** (DLT -0.9407 元/注)。
  方案之间唯一能差的是:
     · 你花多少钱 (花费)
     · "至少中一注"的概率 (中奖率)  ← 只跟**结构**有关, 跟号码冷热无关
     · 命中的是哪个奖级 (期望值不变, 只是方差分布不同)
  号码冷热对中奖率**没有任何影响** (见 scripts/hot_illusion.py 的实验)。
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

from data.dan_tuo_exact import exact_dan_tuo
from data.games import get_game
from scripts.analyze_dantuo import load_stats, rank_table


def build_schemes(fp, bp, fd0, bd0, f_rank, b_rank, fr, br):
    """生成候选方案列表 [(标签, 前胆, 前拖, 后胆, 后拖), ...]"""

    def hot_of(pool, rank, k):
        return sorted(pool, key=lambda v: rank[v])[:k]

    def cold_of(pool, rank, k):
        return sorted(pool, key=lambda v: -rank[v])[:k]

    def miss_of(pool, miss, k):
        return sorted(pool, key=lambda v: -int(miss[v]))[:k]

    ft0 = [x for x in fp if x not in fd0]
    bt0 = [x for x in bp if x not in bd0]

    schemes = [
        ('A. 原方案 (你的)',
         fd0, ft0, bd0, bt0),

        ('B. 热号胆版 (前35+32 / 后12)',
         hot_of(fp, f_rank, 2), [x for x in fp if x not in hot_of(fp, f_rank, 2)],
         hot_of(bp, b_rank, 1), [x for x in bp if x not in hot_of(bp, b_rank, 1)]),

        ('C. 去后区胆 (后区全拖)',
         fd0, ft0, [], list(bp)),

        ('D. 双区零胆全覆盖',
         [], list(fp), [], list(bp)),

        ('E. 省钱版 (拖码减半)',
         fd0, ft0[:6], bd0, bt0[:3]),

        ('F. 遗漏胆版 (前23 / 后09)',
         miss_of(fp, fr['miss'], 1), [x for x in fp if x not in miss_of(fp, fr['miss'], 1)],
         miss_of(bp, br['miss'], 1), [x for x in bp if x not in miss_of(bp, br['miss'], 1)]),

        ('G. 冷号胆版 (前区最冷)',
         cold_of(fp, f_rank, 1), [x for x in fp if x not in cold_of(fp, f_rank, 1)],
         bd0, bt0),
    ]
    return schemes


def main():
    ap = argparse.ArgumentParser(description='胆拖方案对比 (精确超几何)')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-pool', default='2 4 6 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-pool', default='2 4 6 9 12')
    ap.add_argument('--front-dan', default='6')
    ap.add_argument('--back-dan', default='4')
    args = ap.parse_args()

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split())

    fp, bp = nums(args.front_pool), nums(args.back_pool)
    fd0, bd0 = nums(args.front_dan), nums(args.back_dan)

    st = load_stats(args.game)
    cfg = st['cfg']
    fr, br = st['front'], st['back']
    f_rank, b_rank = rank_table(fr), rank_table(br)

    print()
    print('=' * 96)
    print(f'  胆拖方案对比 (精确超几何)  —  {cfg.name}   样本 {st["n"]} 期')
    print(f'  前区号码池: {fp}')
    print(f'  后区号码池: {bp}')
    print('=' * 96)
    print()

    rows = []
    for label, fd, ft, bd, bt in build_schemes(fp, bp, fd0, bd0, f_rank, b_rank, fr, br):
        try:
            r = exact_dan_tuo(args.game, fd, ft, bd, bt)
        except ValueError as e:
            print(f'  [{label}] 结构不合法: {e}')
            continue
        r['label'] = label
        rows.append(r)

    # ---- 主对比表 ----
    print(f'  {"方案":<26}{"注数":>8}{"花费":>9}{"期望净收益":>12}'
          f'{"中奖率":>10}{"≥3等奖":>10}{"全灭概率":>11}')
    print('  ' + '-' * 86)
    for r in rows:
        big = sum(p['prob_any'] for p in r['prize_dist']
                  if p['money'] >= 3000) * 100
        print(f'  {r["label"]:<26}{r["n_bets"]:>8,}{r["cost"]:>9,.0f}'
              f'{r["expected_net"]:>+12,.0f}{r["win_rate"]:>9.2f}%'
              f'{big:>9.3f}%{r["lose_rate"]:>10.2f}%')
    print('  ' + '-' * 86)
    print()

    # ---- 各方案奖级结构 ----
    print('  【各方案奖级命中概率 (至少中一注)】')
    for r in rows:
        print(f'    {r["label"]}   {r["n_bets"]:,} 注 / {r["cost"]:,.0f} 元')
        for p in r['prize_dist']:
            if p['money'] <= 0:
                continue
            bar = '█' * int(p['prob_any'] * 100)
            print(f'      {p["label"]:<7}{p["money"]:>10,.0f}元  '
                  f'{p["prob_any"] * 100:>8.4f}%  {bar}')
    print()

    # ---- 具体号码 ----
    print('  【各方案具体号码】')
    for r in rows:
        print(f'    {r["label"]}:')
        print(f'      前区 胆 {" ".join(f"{v:02d}" for v in r["front_dan"]) or "(无)"}'
              f'   拖 {" ".join(f"{v:02d}" for v in r["front_tuo"])}')
        print(f'      后区 胆 {" ".join(f"{v:02d}" for v in r["back_dan"]) or "(无)"}'
              f'   拖 {" ".join(f"{v:02d}" for v in r["back_tuo"])}')
    print()

    # ---- 结论 ----
    print('  ' + '=' * 86)
    print('  【诚实结论】')
    print('  ' + '=' * 86)
    per_bet = rows[0]['expected_net'] / rows[0]['n_bets'] if rows[0]['n_bets'] else 0
    print(f'    · 每个方案的**单注期望净收益都是 {per_bet:+.4f} 元** —— 完全一样。')
    print(f'      方案之间差的只是「花多少」和「多容易中」, 期望值改不了。')
    print(f'    · 中奖率高低**只由结构决定** (胆码越多 → 共享约束越强 → 中奖率越低),')
    print(f'      与号码冷热**完全无关** —— 这是 v1.6.0 热号幻觉实验的结论。')
    best = max(rows, key=lambda x: x['win_rate'])
    cheapest = min(rows, key=lambda x: x['cost'])
    print(f'    · 中奖率最高: {best["label"]}  {best["win_rate"]:.2f}%'
          f'  ({best["n_bets"]:,} 注 / {best["cost"]:,.0f} 元)')
    print(f'    · 最省钱:     {cheapest["label"]}  {cheapest["cost"]:,.0f} 元'
          f'  ({cheapest["n_bets"]:,} 注, 中奖率 {cheapest["win_rate"]:.2f}%)')
    print()


if __name__ == '__main__':
    main()
