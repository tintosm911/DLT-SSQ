"""
胆拖精确求解器测试
==================
验证 data/dan_tuo_exact.py 的三个核心性质:

  T1 期望返奖 == 单注期望 × 注数            (误差 < 1e-9)
  T2 中奖率只取决于胆码**个数**, 与具体选哪几个号无关  (bit-for-bit 相同)
  T3 中奖率与独立蒙特卡洛一致               (误差在统计涨落内)
"""
import sys
import itertools
from math import comb
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.dan_tuo_exact import exact_dan_tuo
from data.pick_advisor import Pick, calc_expected_prize
from data.games import get_game, get_prize_rules

FP = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32, 35]
BP = [2, 4, 6, 9, 12]


def _single_win_prob(game: str) -> float:
    """独立算单注中奖概率 (超几何)"""
    cfg = get_game(game)
    lut = {(c[0], c[1]): i[1] for c, i in get_prize_rules(game)}
    cnt = 0
    for nf in range(cfg.front_count + 1):
        for nb in range(cfg.back_count + 1):
            if lut.get((nf, nb), 0) > 0:
                cnt += (comb(cfg.front_count, nf)
                        * comb(cfg.front_range - cfg.front_count, cfg.front_count - nf)
                        * comb(cfg.back_count, nb)
                        * comb(cfg.back_range - cfg.back_count, cfg.back_count - nb))
    total = comb(cfg.front_range, cfg.front_count) * comb(cfg.back_range, cfg.back_count)
    return cnt / total


def test_t1_expected_return_matches_single_bet():
    """期望返奖 == 单注期望 × 注数"""
    cases = [
        ('dlt', [6], [2, 4, 10, 14, 16, 18, 23, 26, 32, 35], [4], [2, 6, 9, 12]),
        ('dlt', [], [1, 2, 3, 4, 5, 6, 7], [], list(range(1, 13))),
        ('dlt', [1, 2, 3, 4], [5], [1], [2]),
        ('ssq', [3], [1, 2, 4, 5, 6, 7, 8, 9, 10], [7], [1, 2, 3, 4, 5, 6, 8]),
    ]
    for game, fd, ft, bd, bt in cases:
        cfg = get_game(game)
        r = exact_dan_tuo(game, fd, ft, bd, bt)
        e1, _, _, _ = calc_expected_prize(
            game, Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count))
        assert abs(e1 * r['n_bets'] - r['expected_return']) < 1e-9, (
            f'{game} {r["n_bets"]}注 期望不符: {r["expected_return"]} vs {e1 * r["n_bets"]}')


def test_t2_single_ticket_probability():
    """单注未中概率 == 独立超几何精确值"""
    for game in ('dlt', 'ssq'):
        cfg = get_game(game)
        r = exact_dan_tuo(game, [], list(range(1, cfg.front_count + 3)),
                          [], list(range(1, cfg.back_count + 3)))
        p = _single_win_prob(game)
        assert abs((1 - p) - r['empty_prob']) < 1e-12, (
            f'{game} 单注未中概率不符: {r["empty_prob"]} vs {1 - p}')


def test_t3_win_rate_depends_only_on_dan_count():
    """
    定理: 固定号码池下, 中奖率只取决于胆码**个数**,
    与"胆码具体选哪几个号"完全无关 (开奖对称性)。
    """
    for k, m in ((1, 1), (2, 0), (0, 2), (2, 1)):
        sigs = set()
        for fp_iv in itertools.islice(itertools.combinations(FP, k), 0, 12):
            for bp_iv in itertools.islice(itertools.combinations(BP, m), 0, 12):
                fd = sorted(fp_iv)
                ft = sorted(x for x in FP if x not in set(fd))
                bd = sorted(bp_iv)
                bt = sorted(x for x in BP if x not in set(bd))
                r = exact_dan_tuo('dlt', fd, ft, bd, bt)
                sigs.add((r['n_bets'], round(r['expected_return'], 8),
                          round(r['win_rate'], 12)))
        assert len(sigs) == 1, f'前胆{k}/后胆{m}: 中奖率随号码变化了 → 定理被打破: {sigs}'


def test_t4_win_rate_matches_monte_carlo():
    """中奖率与独立蒙特卡洛一致 (30 万次, 向量化)"""
    import numpy as np
    game, fd, ft, bd, bt = ('dlt', [6], FP[1:], [4], BP[:4])
    ft = [2, 4, 10, 14, 16, 18, 23, 26, 32, 35]
    bt = [2, 6, 9, 12]
    cfg = get_game(game)
    r = exact_dan_tuo(game, fd, ft, bd, bt)

    tickets = [(sorted(list(fd) + list(fc)), sorted(list(bd) + list(bc)))
               for fc in itertools.combinations(ft, cfg.front_count - len(fd))
               for bc in itertools.combinations(bt, cfg.back_count - len(bd))]
    lut = {(c[0], c[1]): float(i[1]) for c, i in get_prize_rules(game)}
    money = np.zeros((cfg.front_count + 1, cfg.back_count + 1), dtype=float)
    for (k, j), mv in lut.items():
        money[k, j] = mv

    f_sel = np.zeros((len(tickets), cfg.front_range), dtype=np.int8)
    b_sel = np.zeros((len(tickets), cfg.back_range), dtype=np.int8)
    for i, (f, b) in enumerate(tickets):
        for v in f:
            f_sel[i, v - 1] = 1
        for v in b:
            b_sel[i, v - 1] = 1

    rng = np.random.default_rng(2026)
    n_sim, chunk, wins, done = 200_000, 2000, 0, 0
    while done < n_sim:
        m = min(chunk, n_sim - done)
        d_f = np.zeros((m, cfg.front_range), dtype=np.int8)
        d_b = np.zeros((m, cfg.back_range), dtype=np.int8)
        for i in range(m):
            d_f[i, rng.choice(cfg.front_range, cfg.front_count, replace=False)] = 1
            d_b[i, rng.choice(cfg.back_range, cfg.back_count, replace=False)] = 1
        nf = d_f @ f_sel.T
        nb = d_b @ b_sel.T
        wins += int((money[nf, nb] > 0).any(axis=1).sum())
        done += m
    mc = wins / n_sim * 100
    se = (mc * (100 - mc) / n_sim) ** 0.5
    assert abs(mc - r['win_rate']) < max(5 * se, 0.05), (
        f'中奖率不符: 精确 {r["win_rate"]:.4f}% vs MC {mc:.4f}% (5σ={5*se:.4f}%)')


def test_t5_known_values():
    """已算好的基准值 (回归保护)"""
    r = exact_dan_tuo('dlt', [6], [2, 4, 10, 14, 16, 18, 23, 26, 32, 35],
                      [4], [2, 6, 9, 12])
    assert r['n_bets'] == 840, f'注数 {r["n_bets"]} != 840'
    assert r['cost'] == 1680.0
    assert abs(r['expected_net'] + 790.22) < 0.01, f'期望净收益 {r["expected_net"]}'
    assert abs(r['win_rate'] - 42.9661894083) < 1e-6, f'中奖率 {r["win_rate"]}'

    # 零胆全覆盖 (前 11 选 5 × 后 5 选 2)
    r2 = exact_dan_tuo('dlt', [], FP, [], BP)
    assert r2['n_bets'] == 4620
    assert abs(r2['win_rate'] - 47.4297050198) < 1e-6, f'中奖率 {r2["win_rate"]}'


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f'  OK   {fn.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL {fn.__name__}: {e}')
    print(f'\n{len(fns) - failed}/{len(fns)} 通过')
    sys.exit(1 if failed else 0)
