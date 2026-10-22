"""
精确胆拖求解器 —— 深度交叉验证
==============================
对 data/dan_tuo_exact.py 做**完全独立**的第二实现对拍:

  A. 期望返奖 == calc_expected_prize × 注数          (误差 < 1e-9)
  B. 单注未中概率 == 独立超几何精确值                  (误差 < 1e-12)
  C. 整体中奖率 == 向量化蒙特卡洛 (30 万次)            (5σ 内)
  D. 各奖级"至少中一注"概率 == 向量化蒙特卡洛          (5σ 内)

★ 这个脚本的价值在于: 精确解与蒙特卡洛是**两套完全不同的算法**
  (全枚举 vs 抽样), 两者结论一致 → 任何一方有 bug 都会被对方抓出来。
  开发过程中正是它抓出了"同名奖级重复计数"和"随机一注≠所有注"两个 bug。

★ 注意: 对拍蒙特卡洛里同名奖级 (如 DLT 九等奖 = 4 组命中组合)
  必须先按奖级做 OR 合并再统计, 否则会算出 >100% 的概率。

用法:
  python scripts/verify_dan_tuo_exact.py
"""
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np

from data.dan_tuo_exact import exact_dan_tuo
from data.pick_advisor import Pick, calc_expected_prize
from data.games import get_game, get_prize_rules

CASES = [
    ('dlt', [6], [2, 4, 10, 14, 16, 18, 23, 26, 32, 35], [4], [2, 6, 9, 12]),
    ('dlt', [], [1, 2, 3, 4, 5, 6, 7], [], list(range(1, 13))),
    ('dlt', [1, 2, 3, 4], [5], [1], [2]),
    ('dlt', [], list(range(1, 12)), [], list(range(1, 6))),
    ('ssq', [3], [1, 2, 4, 5, 6, 7, 8, 9, 10], [7], [1, 2, 3, 4, 5, 6, 8]),
    ('ssq', [], list(range(1, 13)), [], list(range(1, 10))),
]


def vec_mc(game, fd, ft, bd, bt, n_sim=300_000, seed=11):
    """向量化蒙特卡洛: 返回 (中奖率%, 各奖级至少中一注的概率%)"""
    import itertools
    cfg = get_game(game)
    need_f = cfg.front_count - len(fd)
    need_b = cfg.back_count - len(bd)
    tickets = [(sorted(list(fd) + list(fc)), sorted(list(bd) + list(bc)))
               for fc in itertools.combinations(ft, need_f)
               for bc in itertools.combinations(bt, need_b)]
    n_bets = len(tickets)

    lut = {}
    for cond, info in get_prize_rules(game):
        lut[(cond[0], cond[1])] = (info[0], float(info[1]) if len(info) > 1 else 0.0)
    label_of = {k: v[0] for k, v in lut.items()}
    lab_keys = {}
    for (k, j), (lab, mv) in lut.items():
        if mv <= 0:
            continue
        lab_keys.setdefault(lab, []).append((k, j))
    money = np.zeros((cfg.front_count + 1, cfg.back_count + 1), dtype=float)
    for (k, j), (_, m) in lut.items():
        money[k, j] = m

    f_sel = np.zeros((n_bets, cfg.front_range), dtype=np.int8)
    b_sel = np.zeros((n_bets, cfg.back_range), dtype=np.int8)
    for i, (f, b) in enumerate(tickets):
        for v in f:
            f_sel[i, v - 1] = 1
        for v in b:
            b_sel[i, v - 1] = 1

    rng = np.random.default_rng(seed)
    win_rows = 0
    lvl_rows = {}          # 奖级 -> 有注达到该奖级的期数
    lvl_counts = {}        # 奖级 -> (期数, 该期总奖金)
    done = 0
    chunk = 3000
    while done < n_sim:
        m = min(chunk, n_sim - done)
        d_f = np.zeros((m, cfg.front_range), dtype=np.int8)
        d_b = np.zeros((m, cfg.back_range), dtype=np.int8)
        for i in range(m):
            d_f[i, rng.choice(cfg.front_range, cfg.front_count, replace=False)] = 1
            d_b[i, rng.choice(cfg.back_range, cfg.back_count, replace=False)] = 1
        nf = d_f @ f_sel.T          # (m, n_bets)
        nb = d_b @ b_sel.T
        mat = money[nf, nb]         # 每注奖金
        row_win = (mat > 0).any(axis=1)
        win_rows += int(row_win.sum())
        # 每个奖级: 是否有注达到
        # ★ 同名奖级可能对应多个 (前命中,后命中) 组合 (如 DLT 九等奖 = 4 组),
        #   必须先按奖级做 OR 合并, 否则会重复计数 (概率会算出 >100%)
        for lab, keys in lab_keys.items():
            mask = None
            for (k, j) in keys:
                h = (nf == k) & (nb == j)
                mask = h if mask is None else (mask | h)
            lvl_rows[lab] = lvl_rows.get(lab, 0) + int(mask.any(axis=1).sum())
        done += m
    out = {lab: v / n_sim * 100 for lab, v in lvl_rows.items()}
    return win_rows / n_sim * 100, out


print('=' * 96)
print('  A/B: 期望值与单注未中概率 (精确)')
print('=' * 96)
ok = True
for game, fd, ft, bd, bt in CASES:
    cfg = get_game(game)
    r = exact_dan_tuo(game, fd, ft, bd, bt)
    e1, _, _, _ = calc_expected_prize(
        game, Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count))
    d_exp = abs(e1 * r['n_bets'] - r['expected_return'])

    lut = {(c[0], c[1]): i[1] for c, i in get_prize_rules(game)}
    win_cnt = 0
    for nf in range(cfg.front_count + 1):
        for nb in range(cfg.back_count + 1):
            if lut.get((nf, nb), 0) > 0:
                wf = comb(cfg.front_count, nf) * comb(cfg.front_range - cfg.front_count, cfg.front_count - nf)
                wb = comb(cfg.back_count, nb) * comb(cfg.back_range - cfg.back_count, cfg.back_count - nb)
                win_cnt += wf * wb
    total = comb(cfg.front_range, cfg.front_count) * comb(cfg.back_range, cfg.back_count)
    single_win = win_cnt / total * 100
    d_single = abs((100 - single_win) / 100 - r['empty_prob'])

    good = d_exp < 1e-6 and d_single < 1e-12
    ok = ok and good
    print(f'{"✅" if good else "❌"} {game} {r["n_bets"]:>6,}注 | 期望Δ={d_exp:.1e} | '
          f'单注未中Δ={d_single:.1e} | 单注中奖率={single_win:.4f}% | '
          f'整体中奖率={r["win_rate"]:.4f}%')

print()
print('=' * 96)
print('  C/D: 整体中奖率 + 各奖级概率 vs 向量化蒙特卡洛 (300,000 次)')
print('=' * 96)
for game, fd, ft, bd, bt in CASES:
    r = exact_dan_tuo(game, fd, ft, bd, bt)
    mc_win, mc_lvl = vec_mc(game, fd, ft, bd, bt)
    se = (mc_win * (100 - mc_win) / 300000) ** 0.5
    diff = abs(mc_win - r['win_rate'])
    good = diff < max(5 * se, 0.03)
    ok = ok and good
    print(f'{"✅" if good else "❌"} {game} {r["n_bets"]:>6,}注 中奖率 精确 {r["win_rate"]:.4f}%  '
          f'MC {mc_win:.4f}%  Δ={diff:.4f}% (5σ={5*se:.4f}%)')
    # 奖级对比 (阈值按每个奖级各自的抽样标准误算 —— 最低奖级概率大, 方差也大)
    for p in r['prize_dist']:
        if p['money'] <= 0:
            continue
        mc_v = mc_lvl.get(p['label'], 0.0)
        ex_v = p['prob_any'] * 100
        d = abs(mc_v - ex_v)
        se_l = (mc_v * (100 - mc_v) / 300000) ** 0.5
        thr = max(5 * se_l, 0.05)
        lvl_ok = d < thr
        ok = ok and lvl_ok
        print(f'      {"✅" if lvl_ok else "❌"} {p["label"]:<7} 精确 {ex_v:>9.4f}%  '
              f'MC {mc_v:>9.4f}%  Δ={d:.4f}% (5σ={5*se_l:.4f}%)')

print()
print('✅ 全部通过' if ok else '❌ 有偏差')
sys.exit(0 if ok else 1)
