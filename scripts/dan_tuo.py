"""
胆拖投注分析器 (大乐透 / 双色球通用)
==================================
胆拖 = 胆码 (必选) + 拖码 (从中补足)

本脚本回答 4 个问题:
  1. 这一注到底展开成多少注?  ��多少钱?
  2. 这 70 注的期望净收益是多少?
  3. 100 万次模拟开奖, 你的结果分布长什么样?
  4. [关键] 胆拖 vs 随机买同样多注, 有区别吗?

用法:
  python scripts/dan_tuo.py
  python scripts/dan_tuo.py --front-dan 04 09 --front-tuo 02 07 12 22 23 29 32 \\
                            --back-dan 04 --back-tuo 05 08
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

import numpy as np

from data.games import get_game
from data.pick_advisor import Pick, PickAdvisor, calc_expected_prize, judge_prize

SEP = '=' * 74


# ============================================================
# 胆拖解析
# ============================================================
def parse_flat(s: str) -> list:
    """把 '0409' 或 '04 09' 或 '04,09' 都解析成 [4, 9]"""
    if not s:
        return []
    if ',' in s or ' ' in s:
        return sorted(int(x) for x in s.replace(',', ' ').split())
    # 连续数字串: 每两位一组
    return sorted(int(s[i:i + 2]) for i in range(0, len(s), 2))


def expand_dan_tuo(front_dan, front_tuo, back_dan, back_tuo, game):
    """展开胆拖成所有具体注"""
    cfg = get_game(game)
    need_f = cfg.front_count - len(front_dan)
    need_b = cfg.back_count - len(back_dan)

    if need_f < 0:
        raise ValueError(f'胆码数超过要求: 前区要 {cfg.front_count} 个, 给了 {len(front_dan)} 个胆码')
    if need_b < 0:
        raise ValueError(f'胆码数超过要求: 后区要 {cfg.back_count} 个, 给了 {len(back_dan)} 个胆码')

    front_combos = list(combinations(front_tuo, need_f))
    back_combos = list(combinations(back_tuo, need_b))

    tickets = []
    for fc in front_combos:
        for bc in back_combos:
            tickets.append((
                sorted(list(front_dan) + list(fc)),
                sorted(list(back_dan) + list(bc)),
            ))
    return tickets


def validate(numbers, lo, hi, label, dan, tuo):
    """校验号码范围与重复"""
    errs = []
    all_nums = list(numbers)
    if len(set(all_nums)) != len(all_nums):
        errs.append(f'{label}: 有重复号码')
    for n in all_nums:
        if not (lo <= n <= hi):
            errs.append(f'{label}: 号码 {n:02d} 超出范围 {lo}-{hi}')
    dup = set(dan) & set(tuo)
    if dup:
        errs.append(f'{label}: 号码 {sorted(dup)} 同时出现在胆码和拖码')
    return errs


# ============================================================
# 算法评分
# ============================================================
def score_numbers(game, front_nums, back_nums, df, window=300):
    """跑 7 算法给这些号码打分"""
    from core import compute_all_heat_scores
    cfg = get_game(game)
    sub = df.tail(window)
    if sub.empty:
        return {}, {}

    fh, bh = cfg.front_range, cfg.back_range
    f_mat = np.zeros((len(sub), fh), dtype=int)
    b_mat = np.zeros((len(sub), bh), dtype=int)
    for i, (_, row) in enumerate(sub.iterrows()):
        for j in range(cfg.front_count):
            n = int(row[f'front_{j+1}'])
            if 1 <= n <= fh:
                f_mat[i, n - 1] = 1
        for j in range(cfg.back_count):
            n = int(row[f'back_{j+1}'])
            if 1 <= n <= bh:
                b_mat[i, n - 1] = 1

    def pct(scores, nums):
        ranks = np.argsort(np.argsort(scores))
        nmax = len(scores)
        return {n: round(float(ranks[n - 1] / max(1, nmax - 1) * 100), 1) for n in nums}

    fs = compute_all_heat_scores(f_mat, n_range=fh, window=min(50, len(sub)))
    bs = compute_all_heat_scores(b_mat, n_range=bh, window=min(50, len(sub)))

    out = {}
    for algo, sc in fs.items():
        out[algo] = pct(sc, front_nums)
    for algo, sc in bs.items():
        out[f'{algo}_back'] = pct(sc, back_nums)

    # 平均
    avg = {}
    for n in front_nums:
        vals = [out[a][n] for a in out if not a.endswith('_back') and n in out[a]]
        avg[n] = round(sum(vals) / len(vals), 1) if vals else 50.0
    for n in back_nums:
        vals = [out[a][n] for a in out if a.endswith('_back') and n in out[a]]
        avg[n] = round(sum(vals) / len(vals), 1) if vals else 50.0
    return out, avg


# ============================================================
# 蒙特卡洛: 胆拖 vs 随机
# ============================================================
def judge_one_tier(game, nf, nb):
    """按 (前区命中 nf, 后区命中 nb) 返回 (奖级名, 奖金)"""
    from data.games import get_prize_rules
    for cond, info in get_prize_rules(game):
        if cond[0] == nf and cond[1] == nb:
            return info[0], (info[1] if isinstance(info, (tuple, list)) and len(info) > 1 else 0)
    return '未中', 0.0


def monte_carlo(tickets, game, n_draws=1_000_000, seed=42):
    """向量化模拟 n_draws 次开奖, 统计胆拖票的中奖分布"""
    cfg = get_game(game)
    rng = np.random.default_rng(seed)

    fr, br = cfg.front_range, cfg.back_range
    fc, bc = cfg.front_count, cfg.back_count

    # (n_tickets, fc) 布尔命中矩阵 + (n_tickets, bc)
    ft = sorted(tickets, key=lambda t: (t[0], t[1]))
    # one-hot 矩阵按号码范围分配 (前区 1..fr, 后区 1..br)
    front_sel = np.zeros((len(ft), fr), dtype=np.int32)
    back_sel = np.zeros((len(ft), br), dtype=np.int32)
    for i, (f, b) in enumerate(ft):
        for j, n in enumerate(f):
            front_sel[i, n - 1] = 1
        for j, n in enumerate(b):
            back_sel[i, n - 1] = 1

    # 奖级查表: (nf, nb) -> money
    lookup = np.zeros((fc + 1, bc + 1), dtype=np.float64)
    from data.games import get_prize_rules
    label_of = {}
    for cond, info in get_prize_rules(game):
        nf, nb = cond[0], cond[1]
        money = info[1] if isinstance(info, (tuple, list)) and len(info) > 1 else 0
        lookup[nf, nb] = money
        label_of[(nf, nb)] = info[0]

    chunk = 20_000
    done = 0
    wins = np.zeros(n_draws, dtype=bool)
    total_returns = np.zeros(n_draws, dtype=np.float64)
    prize_counts = {}

    while done < n_draws:
        m = min(chunk, n_draws - done)
        # (m, fr) 开奖矩阵
        dmat_f = np.zeros((m, fr), dtype=np.int32)
        dmat_b = np.zeros((m, br), dtype=np.int32)
        for i in range(m):
            dmat_f[i, rng.choice(fr, fc, replace=False)] = 1
            dmat_b[i, rng.choice(br, bc, replace=False)] = 1

        # 命中数: (m, n_tickets)
        nf_mat = dmat_f @ front_sel.T
        nb_mat = dmat_b @ back_sel.T
        # 奖金: (m, n_tickets)
        money_mat = lookup[nf_mat, nb_mat]
        row_ret = money_mat.sum(axis=1)
        row_hit = (money_mat > 0).any(axis=1)

        sl = slice(done, done + m)
        total_returns[sl] = row_ret
        wins[sl] = row_hit

        # 奖级计数 (向量化: 展平后用 np.unique)
        nz_mask = money_mat > 0
        if nz_mask.any():
            nz_nf = nf_mat[nz_mask]
            nz_nb = nb_mat[nz_mask]
            keys = nz_nf * (bc + 1) + nz_nb
            uk, uc = np.unique(keys, return_counts=True)
            for k, c in zip(uk, uc):
                nf_k, nb_k = int(k) // (bc + 1), int(k) % (bc + 1)
                lab = label_of.get((nf_k, nb_k), '?')
                prize_counts[lab] = prize_counts.get(lab, 0) + int(c)

        done += m
        print(f'  模拟进度 {done:,}/{n_draws:,}', end='\r')

    print()
    return wins, total_returns, prize_counts


# ============================================================
# 主流程
# ============================================================
def main():
    ap = argparse.ArgumentParser(description='胆拖投注分析器')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-dan', default='0409', help='前区胆码, 如 "0409" 或 "04 09"')
    ap.add_argument('--front-tuo', default='02071222232932', help='前区拖码')
    ap.add_argument('--back-dan', default='04', help='后区胆码')
    ap.add_argument('--back-tuo', default='0508', help='后区拖码')
    ap.add_argument('--draws', type=int, default=200_000, help='模拟开奖次数')
    args = ap.parse_args()

    cfg = get_game(args.game)
    price = cfg.ticket_price

    front_dan = parse_flat(args.front_dan)
    front_tuo = parse_flat(args.front_tuo)
    back_dan = parse_flat(args.back_dan)
    back_tuo = parse_flat(args.back_tuo)

    print()
    print(SEP)
    print(f'  胆拖投注分析  —  {cfg.name} ({args.game.upper()})')
    print(SEP)

    # ---- 1. 解析 ----
    print()
    print('  【1】你的号码')
    print(f"      前区胆码: {' '.join(f'{n:02d}' for n in front_dan)}")
    print(f"      前区拖码: {' '.join(f'{n:02d}' for n in front_tuo)}")
    print(f"      后区胆码: {' '.join(f'{n:02d}' for n in back_dan)}")
    print(f"      后区拖码: {' '.join(f'{n:02d}' for n in back_tuo)}")

    errs = []
    errs += validate(front_dan + front_tuo, 1, cfg.front_range, '前区', front_dan, front_tuo)
    errs += validate(back_dan + back_tuo, 1, cfg.back_range, '后区', back_dan, back_tuo)
    if errs:
        print()
        print('  [!] 号码问题:')
        for e in errs:
            print(f'      - {e}')
        return 1

    # ---- 2. 展开 ----
    try:
        tickets = expand_dan_tuo(front_dan, front_tuo, back_dan, back_tuo, args.game)
    except ValueError as e:
        print(f'\n  [!] {e}')
        return 1

    need_f = cfg.front_count - len(front_dan)
    need_b = cfg.back_count - len(back_dan)
    n_front_combos = comb(len(front_tuo), need_f)
    n_back_combos = comb(len(back_tuo), need_b)
    n_tickets = len(tickets)
    total_cost = n_tickets * price

    print()
    print('  【2】展开成多少注 / 花多少钱')
    print(f'      前区: {len(front_dan)} 胆 + 从 {len(front_tuo)} 拖里选 {need_f} '
          f'= C({len(front_tuo)},{need_f}) = {n_front_combos} 种')
    print(f'      后区: {len(back_dan)} 胆 + 从 {len(back_tuo)} 拖里选 {need_b} '
          f'= C({len(back_tuo)},{need_b}) = {n_back_combos} 种')
    print(f'      合计: {n_front_combos} × {n_back_combos} = **{n_tickets} 注**')
    print(f'      花费: {n_tickets} × {price:.0f} 元 = **{total_cost:.0f} 元**')

    # ---- 3. 期望值 ----
    exp1, net1, kelly1, prob1 = calc_expected_prize(args.game, Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count))
    exp_total = exp1 * n_tickets
    net_total = exp_total - total_cost

    print()
    print('  【3】期望值 (数学上一定亏)')
    print(f'      单注期望奖金:   {exp1:.4f} 元')
    print(f'      单注期望净收益: {net1:+.4f} 元')
    print(f'      {n_tickets} 注期望奖金: {exp_total:.2f} 元')
    print(f'      {n_tickets} 注期望净收益: **{net_total:+.2f} 元**')
    print(f'      凯利最优 f*:    **{kelly1:.3f}**  (公式说: 不下注)')
    print(f'      单注一等奖概率: 1/{int(1/prob1):,}')
    print(f'      {n_tickets} 注一等奖概率: 1/{int(1/(prob1*n_tickets)):,}  '
          f'(覆盖倍数 {n_tickets}x)')

    # ---- 4. 算法评分 ----
    print()
    print('  【4】7 算法给这些号码的评分 (基于最近 300 期)')
    try:
        from data.sqlite_storage import SQLiteStorage
        df = SQLiteStorage().load_dataframe(args.game)
        if not df.empty:
            _, avg = score_numbers(args.game, front_dan + front_tuo, back_dan + back_tuo, df)
            for label, nums, dan in (('前区', sorted(front_dan + front_tuo), set(front_dan)),
                                     ('后区', sorted(back_dan + back_tuo), set(back_dan))):
                if not nums:
                    continue
                cells = []
                for n in nums:
                    s = avg.get(n, 50)
                    tag = '胆' if n in dan else '拖'
                    flag = '热' if s >= 70 else ('冷' if s < 30 else '')
                    cells.append(f'{n:02d}({tag})={s:.0f}{flag}')
                print(f'      {label}: ' + '  '.join(cells))
        else:
            print('      (数据库为空, 跳过)')
    except Exception as e:
        print(f'      (评分失败: {e})')

    # ---- 5. 蒙特卡洛 ----
    print()
    print(f'  【5】模拟开奖 {args.draws:,} 次, 看结果分布')
    wins, returns, prize_counts = monte_carlo(tickets, args.game, args.draws)

    n_win = int(wins.sum())
    p_win = n_win / len(wins)
    mean_ret = returns.mean()
    empirical_net = mean_ret - total_cost

    # 剔除大奖后的真实常态 (大奖是极端值, 会严重拉高均值)
    big_win_threshold = 10_000  # 三等奖以上算"大奖"
    big_wins = returns >= big_win_threshold
    n_big = int(big_wins.sum())
    mean_ret_no_big = returns[~big_wins].mean() if (~big_wins).any() else 0.0
    net_no_big = mean_ret_no_big - total_cost

    print()
    print(f'      中奖概率:     {p_win*100:.2f}%  ({n_win:,} / {len(wins):,} 次)')
    print(f'      亏损概率:     {(1-p_win)*100:.2f}%  (一次奖都没中)')
    print(f'      实测平均返奖: {mean_ret:.2f} 元/期')
    print(f'      实测净收益:   {empirical_net:+.2f} 元/期  (含大奖)')

    # 理论最好情况: 假设完美预测, 用每注自己的号码当开奖号
    best_case = 0.0
    for f, b in tickets:
        _, m = judge_prize(args.game, Pick(front=list(f), back=list(b)), list(f), list(b))
        best_case += m

    print()
    print(f'      --- 剔除大奖后的常态 (移除 {n_big:,} 次大奖, 占 {n_big/len(wins)*100:.3f}%) ---')
    print(f'      常态平均返奖: {mean_ret_no_big:.2f} 元/期')
    print(f'      常态净收益:   **{net_no_big:+.2f} 元/期**  <-- 这才是真实期望')
    print(f'      最坏情况:     -{total_cost:.0f} 元 (一次不中)')
    print(f'      理论最好情况: {best_case:,.0f} 元 (完美预测, {n_tickets} 注全中一等奖)')
    if n_big:
        print()
        print(f'      [!] 上面 {empirical_net:+.2f} 元是被 {n_big} 次大奖拉高的假象.')
        print(f'          这就是彩票最有害的地方: 一次大奖能掩盖 {len(wins):,} 次亏损.')

    if prize_counts:
        print()
        print('      各奖级命中次数:')
        for label, cnt in sorted(prize_counts.items(), key=lambda x: -x[1]):
            print(f'        {label:<8} {cnt:>8,} 次')

    # ---- 6. 关键对比: 胆拖 vs 随机 ----
    print()
    print(SEP)
    print('  【6】关键对比: 胆拖 vs 随机买同样多注')
    print(SEP)
    print(f'      两种方式都花 {total_cost:.0f} 元, 买 {n_tickets} 注.')
    print(f'      期望净收益都 = {net_total:+.2f} 元.')
    print()
    print('      胆拖唯一的实际效果: 覆盖更多组合, 所以:')
    print(f'        · 一等奖概率提高 {n_tickets} 倍 (1/{int(1/prob1):,} → 1/{int(1/(prob1*n_tickets)):,})')
    print(f'        · 中小奖概率也提高, 中奖率 {p_win*100:.2f}%')
    print()
    print('      但期望值一点没变 —— 相当于把同样的钱摊开买,')
    print('      赢的次数多了, 每次赢的金额小了. 数学上完全等价.')
    print()
    print('  ' + SEP)
    print(f'  结论: 花了 {total_cost:.0f} 元, 期望净收益 {net_total:+.2f} 元, '
          f'凯利 f*=0')
    print('  ' + SEP)
    print()


if __name__ == '__main__':
    sys.exit(main() or 0)