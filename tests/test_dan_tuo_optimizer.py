"""
胆拖结构优化器测试
==================
覆盖:
  T1 优化器给出的最优解 == 独立穷举的最优解
  T2 预算越大 → 最优中奖率单调不减
  T3 填具体号码后重新计算, 概率与结构完全一致 (号码无关定理的端到端验证)
  T4 目标函数各目标的行为正确
  T5 边界条件 (预算过小 / 非法参数)
"""
import sys
from math import comb
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.dan_tuo_exact import exact_dan_tuo
from data.dan_tuo_optimizer import optimize
from data.games import get_game


FP = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32, 35]
BP = [2, 4, 6, 9, 12]


def _brute_force(game, budget, front_pool, back_pool):
    """独立穷举 (不依赖优化器的代码路径)"""
    cfg = get_game(game)
    best = None
    p_f, p_b = len(front_pool), len(back_pool)
    for k in range(cfg.front_count + 1):
        for t_f in range(cfg.front_count - k, p_f - k + 1):
            for m in range(cfg.back_count + 1):
                for t_b in range(cfg.back_count - m, p_b - m + 1):
                    n = comb(t_f, cfg.front_count - k) * comb(t_b, cfg.back_count - m)
                    cost = n * cfg.ticket_price
                    if cost > budget:
                        continue
                    r = exact_dan_tuo(
                        game,
                        front_pool[:k], front_pool[k:k + t_f],
                        back_pool[:m], back_pool[m:m + t_b])
                    if best is None or r['win_rate'] > best[1]:
                        best = ((k, t_f, m, t_b), r['win_rate'], cost, n)
    return best


def test_t1_optimizer_matches_brute_force():
    """优化器最优解 == 独立穷举最优解"""
    for budget in (100, 500, 1680, 4000):
        r = optimize('dlt', budget=budget, goal='win',
                     front_pool=FP, back_pool=BP, top_n=5)
        bf = _brute_force('dlt', budget, FP, BP)
        assert bf is not None
        b = r['best']
        assert abs(b['win_rate'] - bf[1]) < 1e-9, (
            f'预算 {budget}: 优化器 {b["win_rate"]:.6f}% vs 穷举 {bf[1]:.6f}%')
        assert b['n_bets'] == bf[3], (
            f'预算 {budget}: 注数 {b["n_bets"]} vs {bf[3]}')


def test_t2_monotone_with_budget():
    """预算越大, 最优中奖率单调不减"""
    prev = -1.0
    for budget in (10, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
        r = optimize('dlt', budget=budget, goal='win',
                     front_pool=FP, back_pool=BP, top_n=1)
        w = r['best']['win_rate']
        assert w >= prev - 1e-9, f'预算 {budget}: 中奖率 {w:.4f}% < 上一个 {prev:.4f}%'
        prev = w


def test_t3_filled_numbers_give_same_probability():
    """
    端到端验证"号码无关"定理:
    优化器填了具体号码后, 拿这些号码重算, 概率必须与结构值完全一致。
    """
    for fill in ('hot', 'cold', 'random'):
        r = optimize('dlt', budget=1680, goal='win',
                     front_pool=FP, back_pool=BP, fill=fill, top_n=3)
        for c in r['candidates']:
            again = exact_dan_tuo('dlt', c['front_dan'], c['front_tuo'],
                                  c['back_dan'], c['back_tuo'])
            assert abs(again['win_rate'] - c['win_rate']) < 1e-9, (
                f'fill={fill}: 结构 {c["structure"]} 号码填法影响概率! '
                f'{again["win_rate"]} vs {c["win_rate"]}')
            assert again['n_bets'] == c['n_bets'], (
                f'fill={fill}: 结构 {c["structure"]} 注数不符')


def test_t4_goals_behave():
    """各目标函数行为正确"""
    # win: 中奖率应尽量高
    r = optimize('dlt', budget=1680, goal='win',
                 front_pool=FP, back_pool=BP, top_n=5)
    for c in r['candidates']:
        assert c['win_rate'] <= r['best']['win_rate'] + 1e-9

    # big: >=门槛 概率应尽量高
    r = optimize('dlt', budget=1000, goal='big', big_threshold=3000,
                 front_pool=FP, back_pool=BP, top_n=5)
    for c in r['candidates']:
        assert c['big_prob'] <= r['best']['big_prob'] + 1e-9
    assert r['best']['big_prob'] > 0

    # value: 每元中奖率
    r = optimize('dlt', budget=1000, goal='value',
                 front_pool=FP, back_pool=BP, top_n=5)
    for c in r['candidates']:
        assert (c['win_rate'] / c['cost']) <= (r['best']['win_rate'] /
                                               r['best']['cost']) + 1e-9

    # 期望净收益永远为负 (数学铁律)
    for goal in ('win', 'big', 'value', 'jackpot', 'covernum'):
        r = optimize('dlt', budget=2000, goal=goal,
                     front_pool=FP, back_pool=BP, top_n=3)
        for c in r['candidates']:
            assert c['expected_net'] < 0, f'{goal}: 期望净收益不该 >= 0'


def test_t5_edge_cases():
    """边界条件"""
    # 预算太小
    r = optimize('dlt', budget=1.0, goal='win',
                 front_pool=FP, back_pool=BP, top_n=3)
    assert r['best'] is None, '1 元预算不该有解'

    # 刚好 1 注
    r = optimize('dlt', budget=2.0, goal='win',
                 front_pool=FP, back_pool=BP, top_n=3)
    assert r['best'] is not None
    assert r['best']['n_bets'] == 1
    assert r['best']['cost'] == 2.0

    # 非法目标
    try:
        optimize('dlt', budget=100, goal='nope')
        raise AssertionError('非法目标应当抛异常')
    except ValueError:
        pass

    # 空池 (不限号码)
    r = optimize('dlt', budget=5000, goal='win', top_n=3)
    assert r['best'] is not None
    assert r['best']['n_bets'] * 2 <= 5000

    # 双色球
    r = optimize('ssq', budget=1000, goal='win', top_n=3)
    assert r['best'] is not None
    cfg = get_game('ssq')
    assert r['best']['cost'] == r['best']['n_bets'] * cfg.ticket_price


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
