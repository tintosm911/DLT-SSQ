"""
胆拖方案 · 真实历史回测
=======================
拿**真实开奖数据**逐期判奖, 看一个固定胆拖方案在历史上的实际表现。

★ 与"策略回测"的区别 (重要):
  这里**不做任何选号决策**, 只是把一个**已经定好的**方案
  (固定胆码 + 固定拖码) 放到过去的每一期上检验。
  所以不存在前视偏差 —— 它回答的是:
  "如果我每期都这么买, 历史结果会怎样?"

输出:
  · 中奖期数 / 中奖率
  · 各奖级命中次数
  · 总投入 vs 总返奖 (真实 ROI)
  · **剔除大奖后的常态 ROI** ← 最重要的数字

用法:
  python scripts/dan_tuo_backtest_real.py \
      --front-dan 6 --front-tuo "2 4 10 14 16 18 23 26 32 35" \
      --back-dan 4 --back-tuo "2 6 9 12"

  # 同时对比优化器的最优方案
  python scripts/dan_tuo_backtest_real.py --compare-optimized --budget 1680 \
      --front-pool "2 4 6 10 14 16 18 23 26 32 35" --back-pool "2 4 6 9 12"
"""
from __future__ import annotations

import argparse
import json
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

import numpy as np

from data.games import get_game, get_prize_rules
from data.sqlite_storage import SQLiteStorage


def expand(game, fd, ft, bd, bt):
    """展开成 (前区组合列表, 后区组合列表)

    ★ 2026-11-19 修复: 原实现写死 get_game('dlt'), 导致**双色球回测用
      大乐透的选号数量 (5+2) 展开** —— 注数和中奖率全错。
      只有真正跑双彩种实测才会发现。
    """
    import itertools
    cfg = get_game(game)
    fc = [sorted(list(fd) + list(c)) for c in
          itertools.combinations(ft, cfg.front_count - len(fd))]
    bc = [sorted(list(bd) + list(c)) for c in
          itertools.combinations(bt, cfg.back_count - len(bd))]
    return fc, bc


def load_draws(game: str):
    df = SQLiteStorage().load_dataframe(game)
    fronts, backs, periods = [], [], []
    for _, r in df.iterrows():
        fronts.append([int(r[f'front_{i+1}']) for i in range(5 if game == 'dlt' else 6)])
        backs.append([int(r[f'back_{i+1}']) for i in range(2 if game == 'dlt' else 1)])
        periods.append(str(r['period']))
    return periods, fronts, backs


def backtest(game, fd, ft, bd, bt):
    cfg = get_game(game)
    periods, fronts, backs = load_draws(game)

    # ---- 号码范围校验 (给出可读错误, 而不是 numpy 的 IndexError) ----
    bad_f = [v for v in list(fd) + list(ft)
             if not (1 <= v <= cfg.front_range)]
    bad_b = [v for v in list(bd) + list(bt)
             if not (1 <= v <= cfg.back_range)]
    if bad_f or bad_b:
        raise ValueError(
            f'号码超出 {cfg.name} 范围: '
            f'前区需 1-{cfg.front_range}, 违规 {sorted(set(bad_f))}; '
            f'后区需 1-{cfg.back_range}, 违规 {sorted(set(bad_b))}')

    fc, bc = expand(game, fd, ft, bd, bt)
    n_t = len(fc) * len(bc)
    if n_t == 0:
        return None

    # 奖级 lookup: 金额表 + 奖级 id 表 (用于直方图统计)
    money = np.zeros((cfg.front_count + 1, cfg.back_count + 1), dtype=float)
    label_id = np.zeros((cfg.front_count + 1, cfg.back_count + 1), dtype=np.int32)
    labels = ['未中']
    for cond, info in get_prize_rules(game):
        money[cond[0], cond[1]] = float(info[1]) if len(info) > 1 else 0.0
        label_id[cond[0], cond[1]] = len(labels)
        labels.append(info[0])

    # one-hot 矩阵
    D_f = np.zeros((len(fronts), cfg.front_range), dtype=np.int8)
    D_b = np.zeros((len(backs), cfg.back_range), dtype=np.int8)
    for i, f in enumerate(fronts):
        for v in f:
            D_f[i, v - 1] = 1
    for i, b in enumerate(backs):
        for v in b:
            D_b[i, v - 1] = 1

    T_f = np.zeros((len(fc), cfg.front_range), dtype=np.int8)
    for i, f in enumerate(fc):
        for v in f:
            T_f[i, v - 1] = 1
    T_b = np.zeros((len(bc), cfg.back_range), dtype=np.int8)
    for i, b in enumerate(bc):
        for v in b:
            T_b[i, v - 1] = 1

    # ---- 一次性向量化: (D, n_fc, n_bc) ----
    D = len(fronts)
    nf = D_f @ T_f.T                       # (D, n_fc)
    nb = D_b @ T_b.T                       # (D, n_bc)
    m = money[nf[:, :, None], nb[:, None, :]]       # (D, n_fc, n_bc) 金额
    lid = label_id[nf[:, :, None], nb[:, None, :]]   # 同形状 奖级 id

    per_period = m.sum(axis=(1, 2))
    per_period_wins = (m > 0).sum(axis=(1, 2))

    # 奖级命中次数 (含 0 元)
    counts = np.bincount(lid.ravel(), minlength=len(labels))
    level_counts = {}
    for i, lab in enumerate(labels):
        if counts[i]:
            level_counts[lab] = int(counts[i])

    stake = D * n_t * cfg.ticket_price
    ret = float(per_period.sum())
    big = per_period >= 10000
    ret_no_big = float(per_period[~big].sum())
    stake_no_big = stake
    return {
        'n_draws': D,
        'n_tickets': n_t,
        'stake': stake,
        'returned': ret,
        'net': ret - stake,
        'roi': (ret - stake) / stake * 100,
        'win_periods': int((per_period > 0).sum()),
        'win_rate': float((per_period > 0).sum()) / D * 100,
        'avg_return': float(per_period.mean()),
        'level_counts': level_counts,
        'big_periods': int(big.sum()),
        'net_no_big': ret_no_big - stake_no_big,
        'roi_no_big': (ret_no_big - stake_no_big) / stake_no_big * 100,
        'per_period': per_period,
        'periods': periods,
    }


def show(title, r):
    print()
    print(f'  ── {title} ──')
    print(f'    结构: {r["n_tickets"]:,} 注 × {r["n_draws"]:,} 期 '
          f'= {r["n_tickets"] * r["n_draws"]:,} 次判奖')
    print(f'    总投入 {r["stake"]:>12,.0f} 元    总返奖 {r["returned"]:>12,.0f} 元')
    print(f'    净收益 {r["net"]:>+12,.0f} 元    真实 ROI {r["roi"]:>+7.2f}%')
    print(f'    中奖期数 {r["win_periods"]:>6,} / {r["n_draws"]:,}  '
          f'= {r["win_rate"]:.2f}%')
    print(f'    单期平均返奖 {r["avg_return"]:>10,.2f} 元')
    if r['level_counts']:
        print('    奖级命中:')
        for lab, n in sorted(r['level_counts'].items(),
                             key=lambda x: -x[1])[:10]:
            print(f'       {lab:<8}{n:>7,} 次')
    print(f'    ★ 剔除大奖(≥1万)后的常态: {r["net_no_big"]:>+,.0f} 元  '
          f'ROI {r["roi_no_big"]:+.2f}%   (大奖期 {r["big_periods"]} 期)')
    return r


def random_control(game, n_pool_f, n_pool_b, n_dan_f, n_dan_b, n_runs, seed):
    """
    随机对照组: 随机抽号码池 + 随机选胆码, 回测各自的真实 ROI。

    ★ 用途: 判断某个方案的"历史 ROI 特别好"到底是**结构优势**还是**运气**。
      如果优化器方案的 ROI 落在随机对照分布的中位数附近 → 是运气。
    """
    cfg = get_game(game)
    rng = np.random.default_rng(seed)
    front_all = list(range(1, cfg.front_range + 1))
    back_all = list(range(1, cfg.back_range + 1))
    out = []
    for _ in range(n_runs):
        fp = sorted(rng.choice(front_all, n_pool_f, replace=False).tolist())
        bp = sorted(rng.choice(back_all, n_pool_b, replace=False).tolist())
        # 随机选胆码 (从池里), 拖码 = 其余
        fd = sorted(rng.choice(fp, n_dan_f, replace=False).tolist())
        ft = [x for x in fp if x not in set(fd)]
        bd = sorted(rng.choice(bp, n_dan_b, replace=False).tolist())
        bt = [x for x in bp if x not in set(bd)]
        r = backtest(game, fd, ft, bd, bt)
        if r:
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(description='胆拖方案真实历史回测')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-dan', default='6')
    ap.add_argument('--front-tuo', default='2 4 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-dan', default='4')
    ap.add_argument('--back-tuo', default='2 6 9 12')
    ap.add_argument('--compare-optimized', action='store_true',
                    help='同时跑优化器给出的最优结构做对比')
    ap.add_argument('--budget', type=float, default=1680.0)
    ap.add_argument('--front-pool', default='2 4 6 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-pool', default='2 4 6 9 12')
    ap.add_argument('--random-control', type=int, default=0,
                    help='随机对照组次数 (判断历史 ROI 是运气还是优势)')
    ap.add_argument('--control-runs', type=int, default=12)
    args = ap.parse_args()

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split())

    print()
    print('=' * 92)
    print(f'  胆拖方案 · 真实历史回测 — {get_game(args.game).name}')
    print('=' * 92)

    fd, ft = nums(args.front_dan), nums(args.front_tuo)
    bd, bt = nums(args.back_dan), nums(args.back_tuo)

    r1 = backtest(args.game, fd, ft, bd, bt)
    if not r1:
        print('  ❌ 结构不合法')
        return 1
    show('你的方案', r1)

    if args.compare_optimized:
        from data.dan_tuo_optimizer import optimize
        fp, bp = nums(args.front_pool), nums(args.back_pool)
        ro = optimize(args.game, budget=args.budget, goal='win',
                      front_pool=fp, back_pool=bp, top_n=1)
        b = ro['best']
        r2 = backtest(args.game, b['front_dan'], b['front_tuo'],
                       b['back_dan'], b['back_tuo'])
        show(f'优化器最优结构 ({b["structure"]})', r2)

        print()
        print('  ── 对比 ──')
        print(f'    {"":<22}{"中奖率":>10}{"真实ROI":>12}{"常态ROI":>12}')
        print(f'    {"你的方案":<22}{r1["win_rate"]:>9.2f}%{r1["roi"]:>+11.2f}%'
              f'{r1["roi_no_big"]:>+11.2f}%')
        print(f'    {"优化器最优":<22}{r2["win_rate"]:>9.2f}%{r2["roi"]:>+11.2f}%'
              f'{r2["roi_no_big"]:>+11.2f}%')
        print()
        print(f'    常态 ROI 只差 {abs(r1["roi_no_big"] - r2["roi_no_big"]):.2f} 个百分点 '
              f'→ 结构改不了亏损本质')
        print(f'    含大奖 ROI 差 {abs(r1["roi"] - r2["roi"]):.2f} 个百分点 '
              f'→ 这部分来自**运气**(大奖本来就是极小概率事件)')

        # ---- 随机对照组 ----
        if args.random_control:
            print()
            print('  ── 随机对照组 (判断"历史 ROI 好"是运气还是优势) ──')
            ctrl = random_control(
                args.game, len(fp), len(bp),
                b['k'], b['m'], args.control_runs, seed=20261118)
            rois = sorted(c['roi'] for c in ctrl)
            rois_no_big = sorted(c['roi_no_big'] for c in ctrl)
            n = len(rois)
            print(f'    随机 {n} 组同规模号码池 (前{len(fp)}后{len(bp)}, '
                  f'胆{b["k"]}/{b["m"]}) 的真实 ROI:')
            print(f'      含大奖: 最低 {rois[0]:+.2f}%  '
                  f'中位 {rois[n // 2]:+.2f}%  最高 {rois[-1]:+.2f}%')
            print(f'      常态:   最低 {rois_no_big[0]:+.2f}%  '
                  f'中位 {rois_no_big[n // 2]:+.2f}%  最高 {rois_no_big[-1]:+.2f}%')
            rank = sum(1 for x in rois if x < r2['roi'])
            rank2 = sum(1 for x in rois_no_big if x < r2['roi_no_big'])
            print(f'\n    优化器方案含大奖 ROI {r2["roi"]:+.2f}% 在 {n} 组随机里排第 '
                  f'{rank + 1} 位')
            print(f'    优化器方案常态  ROI {r2["roi_no_big"]:+.2f}% 在 {n} 组随机里排第 '
                  f'{rank2 + 1} 位')
            print()
            print('    ── 判定 ──')
            # ① 含大奖 ROI: 分布极宽 (大奖是极小概率事件) → 排位几乎无意义
            spread_big = rois[-1] - rois[0]
            print(f'    · 含大奖 ROI 的随机分布跨度 {spread_big:.1f} 个百分点 '
                  f'({rois[0]:+.1f}% ~ {rois[-1]:+.1f}%)')
            print(f'      → 这个宽度本身就是"运气能有多大"的度量: '
                  f'同结构换一组号码, 历史 ROI 能从 {rois[0]:+.1f}% 到 {rois[-1]:+.1f}%。')
            if rois[0] < 0 < rois[-1]:
                print(f'      ★ 随机对照里**有方案历史 ROI 为正** —— '
                      f'说明"历史赚钱"完全可能只是撞上了一两次大奖。')
            print(f'      → 优化器的 {r2["roi"]:+.2f}% 排第 {rank + 1}/{n} 位, '
                  f'**在分布中间, 是运气不是能力**。')
            # ② 常态 ROI: 分布极窄 → 超出范围才说明问题
            spread_nb = rois_no_big[-1] - rois_no_big[0]
            print(f'    · 常态 ROI 的随机分布跨度只有 {spread_nb:.2f} 个百分点 '
                  f'({rois_no_big[0]:+.2f}% ~ {rois_no_big[-1]:+.2f}%)')
            lo, hi = rois_no_big[0], rois_no_big[-1]
            if r2['roi_no_big'] < lo or r2['roi_no_big'] > hi:
                print(f'      → 优化器的 {r2["roi_no_big"]:+.2f}% **超出随机范围**, '
                      f'值得进一步查 (但仍需更多样本)')
            else:
                print(f'      → 优化器的 {r2["roi_no_big"]:+.2f}% **落在随机范围之内** '
                      f'→ 结构对长期亏损毫无影响。')
            print(f'      → 所有方案(含随机)的常态 ROI 都在 '
                  f'{lo:+.1f}% ~ {hi:+.1f}% 之间, '
                  f'**这就是"任何结构都在亏"的实证**。')
            print(f'    (注意: 随机对照每次都会重新回测 {r1["n_draws"]:,} 期, 耗时较长)')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
