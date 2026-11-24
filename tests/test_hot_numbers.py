"""
近期热号榜测试
===============
覆盖:
  T1 出现次数统计正确
  T2 期望次数公式正确 (n_draws × draw_count / hi)
  T3 z 值计算正确 (含标准差)
  T4 当前遗漏 / 最大遗漏 计算正确
  T5 真实数据可跑通, 且输出结构完整
"""
import sys
from math import isclose, sqrt
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.hot_numbers import _load, _rank_zone


def _row(rows, num):
    return next(r for r in rows if r['num'] == num)


def test_note_1_counts():
    draws = [[1, 2], [1, 3], [1, 4], [1, 5], [1, 6]]
    rows = _rank_zone(draws, hi=10, n_draws=5, draw_count=2)
    assert _row(rows, 1)['count'] == 5
    assert _row(rows, 2)['count'] == 1
    assert _row(rows, 7)['count'] == 0


def test_note_2_expectation():
    draws = [[1, 2]] * 10
    rows = _rank_zone(draws, hi=10, n_draws=10, draw_count=2)
    # 期望 = 10 × 2 / 10 = 2
    assert isclose(_row(rows, 1)['expect'], 2.0)


def test_note_3_z_score():
    draws = [[1, 2], [1, 3], [1, 4], [1, 5], [1, 6]]
    rows = _rank_zone(draws, hi=10, n_draws=5, draw_count=2)
    # 1 号出现 5 次, 期望 1.0, 标准差 = sqrt(5 × 0.2 × 0.8) = sqrt(0.8)
    sd = sqrt(5 * 0.2 * 0.8)
    assert isclose(_row(rows, 1)['z'], (5 - 1.0) / sd, rel_tol=1e-9)
    # 7 号出现 0 次, 期望 1.0 → z = -1/sd
    assert isclose(_row(rows, 7)['z'], (0 - 1.0) / sd, rel_tol=1e-9)


def test_note_4_omissions():
    draws = [[1, 2], [1, 3], [1, 4], [1, 5], [1, 6]]
    rows = _rank_zone(draws, hi=10, n_draws=5, draw_count=2)
    # 2 号最后一次出现在第 0 期 → 现遗漏 = 5-1-0 = 4
    assert _row(rows, 2)['omission'] == 4
    # 6 号最后一次出现在第 4 期 (最后一期) → 现遗漏 = 0
    assert _row(rows, 6)['omission'] == 0
    # 7 号从没出现 → 现遗漏 = 全部 5 期
    assert _row(rows, 7)['omission'] == 5
    # 3 号出现在第 1 期, 之后第 2,3,4 期都没出 → 最大遗漏 3
    assert _row(rows, 3)['max_omission'] == 3


def test_note_5_real_data_runs():
    for game in ('dlt', 'ssq'):
        periods, fronts, backs = _load(game, 30)
        assert len(periods) == 30
        assert len(fronts) == 30 and len(backs) == 30
        assert all(len(f) in (5, 6) for f in fronts)
        rows = _rank_zone(fronts, 33 if game == 'ssq' else 35, 30,
                          6 if game == 'ssq' else 5)
        assert len(rows) == (33 if game == 'ssq' else 35)
        assert all(r['count'] >= 0 for r in rows)
        # z 值里出现次数最多的号应该是正的
        top = max(rows, key=lambda r: r['count'])
        assert top['z'] > 0
