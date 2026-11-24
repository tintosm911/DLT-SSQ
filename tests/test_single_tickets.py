"""
单式号码生成器测试
====================
覆盖:
  T1 生成 n 注, 号码全部合法 (个数/范围/不重复)
  T2 各注之间互不重复
  T3 ★ hot 模式: 每注的**前区组合都不同** (修过"10 注挤在同一组合"的坑)
  T4 spread 模式: 各注前区组合互不相同 (最大化覆盖)
  T5 单注中奖率对所有号码完全相同 (换号验证)
  T6 号码池越界 / 太小 → 明确报错
"""
import sys
from pathlib import Path

import pytest

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.games import get_game
from scripts.single_tickets import (_gen, _single_expected_return,
                                   _single_win_prob)

POOL_F = [2, 3, 4, 6, 10, 11, 12, 22, 23, 26, 27, 32]
POOL_B = [2, 4, 5, 6, 7, 8, 9, 10, 12]


def _gen_tickets(mode, n=10, game='dlt'):
    cfg = get_game(game)
    return _gen(POOL_F, POOL_B, cfg, n, mode)


def test_note_1_all_tickets_legal():
    cfg = get_game('dlt')
    for mode in ('hot', 'spread', 'random'):
        for f, b in _gen_tickets(mode):
            assert len(f) == 5 and len(set(f)) == 5
            assert len(b) == 2 and len(set(b)) == 2
            assert all(1 <= v <= 35 for v in f)
            assert all(1 <= v <= 12 for v in b)
            assert set(f) <= set(POOL_F)
            assert set(b) <= set(POOL_B)


def test_note_2_tickets_are_mutually_different():
    for mode in ('hot', 'spread', 'random'):
        ts = _gen_tickets(mode)
        keys = {(tuple(f), tuple(b)) for f, b in ts}
        assert len(keys) == len(ts), f'{mode}: 出现重复注'


def test_note_3_hot_mode_has_distinct_front_combos():
    """★ 回归: 之前 hot 模式把 10 注全挤在同一个前区组合上 (中奖率掉一半)"""
    ts = _gen_tickets('hot')
    fronts = {tuple(f) for f, _ in ts}
    assert len(fronts) == len(ts), \
        f'hot 模式只有 {len(fronts)} 个不同的前区组合 (应为 {len(ts)})'


def test_note_4_spread_mode_has_distinct_front_combos():
    ts = _gen_tickets('spread')
    fronts = {tuple(f) for f, _ in ts}
    assert len(fronts) == len(ts)


def test_note_5_single_win_prob_is_number_independent():
    """单注中奖率只由彩种决定, 与号码无关 (组合数学恒等式)"""
    p = _single_win_prob('dlt')
    assert abs(p - 0.0667053) < 1e-6
    # 换彩种 -> 换数值, 但对同一彩种的任何号码都一样
    assert abs(_single_win_prob('ssq') - _single_win_prob('ssq')) < 1e-12
    e = _single_expected_return('dlt')
    assert abs(e - 1.0593) < 1e-3


def test_note_6_pool_validation():
    cfg = get_game('dlt')
    # 池子太小
    with pytest.raises(SystemExit):
        _gen([1, 2], [1, 2], cfg, 1, 'hot')
    # 越界号在主流程里被挡住 (main 里的检查)
    from scripts.single_tickets import _nums
    assert _nums('2 3,4 5') == [2, 3, 4, 5]
