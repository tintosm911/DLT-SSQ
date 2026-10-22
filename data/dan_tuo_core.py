"""
胆拖分析核心库
==============
CLI (scripts/dan_tuo.py) 和 Web GUI (scripts/pick_gui.py) 共用。

对外只暴露一个主入口:
    analyze_dan_tuo(game, front_dan, front_tuo, back_dan, back_tuo,
                     n_draws=..., seed=...) -> dict
返回纯 dict, 可直接 JSON 化给 Web 用。
"""
from __future__ import annotations

from itertools import combinations
from math import comb
from typing import Dict, List

import numpy as np

from data.games import get_game, get_prize_rules
from data.pick_advisor import Pick, calc_expected_prize, judge_prize

# 大奖阈值 (三等奖以上), 用于剔除后算真实常态
BIG_WIN_THRESHOLD = 10_000


# ============================================================
# 解析
# ============================================================
def parse_flat(s: str) -> List[int]:
    """把 '0409' / '04 09' / '04,09' 都解析成 [4, 9]"""
    if not s:
        return []
    if ',' in s or ' ' in s:
        return sorted(int(x) for x in s.replace(',', ' ').split())
    return sorted(int(s[i:i + 2]) for i in range(0, len(s), 2))


def parse_nums(value) -> List[int]:
    """接受 list[int] / str / None"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return sorted(int(x) for x in value)
    return parse_flat(str(value))


def validate(numbers: List[int], lo: int, hi: int, label: str,
             dan: List[int], tuo: List[int]) -> List[str]:
    """校验号码范围与重复, 返回错误列表"""
    errs = []
    if len(set(numbers)) != len(numbers):
        dup = sorted({n for n in numbers if numbers.count(n) > 1})
        errs.append(f'{label}: 号码重复 {dup}')
    for n in numbers:
        if not (lo <= n <= hi):
            errs.append(f'{label}: 号码 {n:02d} 超出范围 {lo}-{hi}')
    both = sorted(set(dan) & set(tuo))
    if both:
        errs.append(f'{label}: 号码 {both} 同时出现在胆码和拖码')
    return errs


# ============================================================
# 展开
# ============================================================
def expand_dan_tuo(front_dan, front_tuo, back_dan, back_tuo, game):
    """展开胆拖成所有具体注, 返回 (tickets, need_f, need_b)"""
    cfg = get_game(game)
    need_f = cfg.front_count - len(front_dan)
    need_b = cfg.back_count - len(back_dan)

    if need_f < 0:
        raise ValueError(
            f'前区胆码过多: 要 {cfg.front_count} 个, 给了 {len(front_dan)} 个胆码')
    if need_b < 0:
        raise ValueError(
            f'后区胆码过多: 要 {cfg.back_count} 个, 给了 {len(back_dan)} 个胆码')
    if need_f > len(front_tuo):
        raise ValueError(
            f'前区拖码不够: 还需要 {need_f} 个, 只有 {len(front_tuo)} 个拖码')
    if need_b > len(back_tuo):
        raise ValueError(
            f'后区拖码不够: 还需要 {need_b} 个, 只有 {len(back_tuo)} 个拖码')

    front_combos = list(combinations(front_tuo, need_f))
    back_combos = list(combinations(back_tuo, need_b))

    tickets = [
        (sorted(list(front_dan) + list(fc)), sorted(list(back_dan) + list(bc)))
        for fc in front_combos
        for bc in back_combos
    ]
    return tickets, need_f, need_b


# ============================================================
# 算法评分
# ============================================================
def score_numbers(game: str, front_nums, back_nums, df, window=300):
    """跑 7 算法给这些号码打百分位分"""
    from core import compute_all_heat_scores
    cfg = get_game(game)
    sub = df.tail(window)
    if sub is None or sub.empty:
        return {}

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
        return {n: round(float(ranks[n - 1] / max(1, nmax - 1) * 100), 1)
                for n in nums}

    fs = compute_all_heat_scores(f_mat, n_range=fh, window=min(50, len(sub)))
    bs = compute_all_heat_scores(b_mat, n_range=bh, window=min(50, len(sub)))

    out = {}
    for algo, sc in fs.items():
        out[algo] = pct(sc, front_nums)
    for algo, sc in bs.items():
        out[f'{algo}_back'] = pct(sc, back_nums)

    avg = {}
    for n in front_nums:
        vals = [out[a][n] for a in out if not a.endswith('_back') and n in out[a]]
        avg[n] = round(sum(vals) / len(vals), 1) if vals else 50.0
    for n in back_nums:
        vals = [out[a][n] for a in out if a.endswith('_back') and n in out[a]]
        avg[n] = round(sum(vals) / len(vals), 1) if vals else 50.0
    return avg


# ============================================================
# 蒙特卡洛 (向量化)
# ============================================================
def monte_carlo(tickets, game: str, n_draws=200_000, seed=42):
    """模拟 n_draws 次开奖, 统计中奖分布"""
    cfg = get_game(game)
    rng = np.random.default_rng(seed)
    fr, br = cfg.front_range, cfg.back_range
    fc, bc = cfg.front_count, cfg.back_count

    ft = sorted(tickets, key=lambda t: (t[0], t[1]))
    # one-hot 按号码范围分配 (前区 1..fr, 后区 1..br)
    front_sel = np.zeros((len(ft), fr), dtype=np.int32)
    back_sel = np.zeros((len(ft), br), dtype=np.int32)
    for i, (f, b) in enumerate(ft):
        for n in f:
            front_sel[i, n - 1] = 1
        for n in b:
            back_sel[i, n - 1] = 1

    # 奖级查表
    lookup = np.zeros((fc + 1, bc + 1), dtype=np.float64)
    label_of = {}
    for cond, info in get_prize_rules(game):
        nf, nb = cond[0], cond[1]
        lookup[nf, nb] = (info[1] if isinstance(info, (tuple, list))
                          and len(info) > 1 else 0)
        label_of[(nf, nb)] = info[0]

    wins = np.zeros(n_draws, dtype=bool)
    returns = np.zeros(n_draws, dtype=np.float64)
    prize_counts = {}

    chunk = 20_000
    done = 0
    while done < n_draws:
        m = min(chunk, n_draws - done)
        dmat_f = np.zeros((m, fr), dtype=np.int32)
        dmat_b = np.zeros((m, br), dtype=np.int32)
        for i in range(m):
            dmat_f[i, rng.choice(fr, fc, replace=False)] = 1
            dmat_b[i, rng.choice(br, bc, replace=False)] = 1

        nf_mat = dmat_f @ front_sel.T
        nb_mat = dmat_b @ back_sel.T
        money_mat = lookup[nf_mat, nb_mat]

        sl = slice(done, done + m)
        returns[sl] = money_mat.sum(axis=1)
        wins[sl] = (money_mat > 0).any(axis=1)

        nz = money_mat > 0
        if nz.any():
            keys = nf_mat[nz] * (bc + 1) + nb_mat[nz]
            uk, uc = np.unique(keys, return_counts=True)
            for k, c in zip(uk, uc):
                lab = label_of.get((int(k) // (bc + 1), int(k) % (bc + 1)), '?')
                prize_counts[lab] = prize_counts.get(lab, 0) + int(c)

        done += m

    return wins, returns, prize_counts


# ============================================================
# 主入口
# ============================================================
def analyze_dan_tuo(game: str,
                    front_dan, front_tuo, back_dan, back_tuo,
                    n_draws=200_000, seed=42,
                    score_window=300, recent_df=None) -> Dict:
    """
    完整分析一注胆拖, 返回可 JSON 化的 dict。

    Raises: ValueError (号码非法 / 拖码不够)
    """
    cfg = get_game(game)
    price = cfg.ticket_price

    fd, ft = parse_nums(front_dan), parse_nums(front_tuo)
    bd, bt = parse_nums(back_dan), parse_nums(back_tuo)

    errs = []
    errs += validate(fd + ft, 1, cfg.front_range, '前区', fd, ft)
    errs += validate(bd + bt, 1, cfg.back_range, '后区', bd, bt)
    if errs:
        raise ValueError('; '.join(errs))

    tickets, need_f, need_b = expand_dan_tuo(fd, ft, bd, bt, game)
    n_tickets = len(tickets)
    total_cost = n_tickets * price

    # 组合数说明
    n_f_combos = comb(len(ft), need_f) if need_f >= 0 else 0
    n_b_combos = comb(len(bt), need_b) if need_b >= 0 else 0

    # 期望值 (取一注算, 与胆拖无关)
    dummy = Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count)
    exp1, net1, kelly1, prob1 = calc_expected_prize(game, dummy)
    exp_total = exp1 * n_tickets
    net_total = exp_total - total_cost

    # 最好情况: 完美预测, 每注用自己号码当开奖号
    best_case = sum(
        judge_prize(game, Pick(front=list(f), back=list(b)), list(f), list(b))[1]
        for f, b in tickets)

    result = {
        'ok': True,
        'game': game,
        'game_name': cfg.name,
        'parse': {
            'front_dan': fd, 'front_tuo': ft,
            'back_dan': bd, 'back_tuo': bt,
        },
        'tickets': {
            'count': n_tickets,
            'need_front': need_f, 'need_back': need_b,
            'n_front_combos': n_f_combos, 'n_back_combos': n_b_combos,
            'unit_price': price,
            'total_cost': total_cost,
        },
        'expected': {
            'per_bet_prize': round(exp1, 4),
            'per_bet_net': round(net1, 4),
            'total_prize': round(exp_total, 2),
            'total_net': round(net_total, 2),
            'kelly': round(kelly1, 3),
            'first_prize_odds': f'1/{int(1 / prob1):,}',
            'cover_first_prize_odds': f'1/{int(1 / (prob1 * n_tickets)):,}',
            'cover_multiple': n_tickets,
        },
        'best_case': best_case,
    }

    # 算法评分
    try:
        if recent_df is None:
            from data.sqlite_storage import SQLiteStorage
            recent_df = SQLiteStorage().load_dataframe(game)
        if recent_df is not None and not recent_df.empty:
            avg = score_numbers(game, fd + ft, bd + bt, recent_df, score_window)
            result['scores'] = {
                'front': {str(n): avg.get(n, 50.0) for n in sorted(fd + ft)},
                'back': {str(n): avg.get(n, 50.0) for n in sorted(bd + bt)},
                'dan': {str(n) for n in fd + bd},
            }
    except Exception:
        result['scores'] = None

    # 蒙特卡洛
    if n_draws > 0:
        wins, returns, prize_counts = monte_carlo(
            tickets, game, n_draws=n_draws, seed=seed)
        n_win = int(wins.sum())
        mean_ret = float(returns.mean())
        big = returns >= BIG_WIN_THRESHOLD
        n_big = int(big.sum())
        mean_no_big = float(returns[~big].mean()) if (~big).any() else 0.0

        result['simulation'] = {
            'draws': n_draws,
            'win_rate': round(n_win / len(wins) * 100, 2),
            'lose_rate': round((1 - n_win / len(wins)) * 100, 2),
            'mean_return': round(mean_ret, 2),
            'net_with_big': round(mean_ret - total_cost, 2),
            'big_count': n_big,
            'big_pct': round(n_big / len(wins) * 100, 3),
            'mean_return_no_big': round(mean_no_big, 2),
            'net_no_big': round(mean_no_big - total_cost, 2),
            'worst_case': -total_cost,
            'prizes': [{'label': k, 'count': v}
                       for k, v in sorted(prize_counts.items(), key=lambda x: -x[1])],
        }

    return result


__all__ = [
    'analyze_dan_tuo',
    'parse_flat', 'parse_nums', 'validate',
    'expand_dan_tuo', 'score_numbers', 'monte_carlo',
    'BIG_WIN_THRESHOLD',
]