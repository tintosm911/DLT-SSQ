"""
胆拖逐注展开器测试
==================
覆盖:
  T1 展开注数 == C(前拖, 需选) × C(后拖, 需选) == 精确求解器的 n_bets
  T2 展开出的每一注都合法 (号码个数正确, 无重复, 号码都在池里)
  T3 展开结果**无重无漏** (集合覆盖所有组合)
  T4 胆码与拖码重叠 / 拖码池不够 / 号码重复 → 明确报错, 不给半份清单
  T5 方案 A 的真实结构 (前 3 胆/7 拖 × 后 1 胆/4 拖) 展开为 84 注
  T6 双色球 (6+1) 支持, 且越界号码 (红球 35) 被拦下
"""
import sys
from math import comb
from pathlib import Path

import pytest

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.dan_tuo_exact import exact_dan_tuo
from data.games import get_game
from scripts.expand_dan_tuo import _check, expand


FD = [2, 4, 6]
FT = [10, 14, 16, 18, 23, 26, 32]
BD = [2]
BT = [4, 6, 9, 12]


def _expand_dlt(fd=FD, ft=FT, bd=BD, bt=BT):
    cfg = get_game('dlt')
    nf = cfg.front_count - len(fd)
    nb = cfg.back_count - len(bd)
    return expand(fd, ft, bd, bt, nf, nb)


def test_note_1_bet_count_matches_formula_and_solver():
    expected = comb(len(FT), 5 - len(FD)) * comb(len(BT), 2 - len(BD))
    assert expected == 84
    assert _check(get_game('dlt'), FD, FT, BD, BT) == expected
    assert len(_expand_dlt()) == expected
    # 与精确求解器口径一致
    r = exact_dan_tuo('dlt', FD, FT, BD, BT)
    assert r['n_bets'] == expected


def test_note_2_every_ticket_is_legal():
    for f, b in _expand_dlt():
        assert len(f) == 5 and len(set(f)) == 5
        assert len(b) == 2 and len(set(b)) == 2
        assert all(1 <= v <= 35 for v in f)
        assert all(1 <= v <= 12 for v in b)
        # 胆码必在, 拖码只能来自拖码池
        assert set(FD).issubset(set(f))
        assert set(BD).issubset(set(b))
        assert set(f) - set(FD) <= set(FT)
        assert set(b) - set(BD) <= set(BT)


def test_note_3_no_duplicate_no_missing():
    tickets = _expand_dlt()
    hashable = {(tuple(f), tuple(b)) for f, b in tickets}
    assert len(hashable) == len(tickets), '展开出现重复注'
    # 逐组合穷举, 与展开结果完全相等
    import itertools
    want = set()
    for fc in itertools.combinations(FT, 5 - len(FD)):
        for bc in itertools.combinations(BT, 2 - len(BD)):
            want.add((tuple(sorted(list(FD) + list(fc))),
                      tuple(sorted(list(BD) + list(bc)))))
    assert hashable == want


def test_note_4_illegal_inputs_raise():
    cfg = get_game('dlt')
    with pytest.raises(SystemExit):
        _check(cfg, [2, 4], [4, 6, 10], [], [1, 2])       # 前区胆拖重叠
    with pytest.raises(SystemExit):
        _check(cfg, [], [1, 2], [], [1, 2])              # 前区拖码不够 (需 5)
    with pytest.raises(SystemExit):
        _check(cfg, [], [1, 2, 3, 4, 5, 5], [], [1, 2])  # 前区号码重复
    with pytest.raises(SystemExit):
        _check(cfg, [1, 2, 3, 4, 5, 6], [], [], [1, 2])  # 前区胆码超 5


def test_note_5_plan_a_structure():
    """方案 A: 前 3 胆/7 拖 × 后 1 胆/4 拖 = 84 注, 168 元"""
    tickets = _expand_dlt()
    assert len(tickets) == 84
    assert len(tickets) * 2 == 168


def test_note_6_ssq_supported_and_range_guarded():
    cfg = get_game('ssq')
    # 红 1 胆/5 拖 (C(5,5)=1) × 蓝 16 拖 (C(16,1)=16) = 16 注
    fd, ft = [2], [4, 6, 10, 14, 16]
    bt = list(range(1, 17))
    assert _check(cfg, fd, ft, [], bt) == 16
    tickets = expand(fd, ft, [], bt, cfg.front_count - len(fd),
                     cfg.back_count)
    assert len(tickets) == 16
    for f, b in tickets:
        assert len(f) == 6 and len(set(f)) == 6
        assert len(b) == 1 and len(set(b)) == 1
    # ★ 越界号码必须被拦下 (双色球红球只到 33)
    with pytest.raises(SystemExit, match='超出范围'):
        _check(cfg, [2], [4, 6, 10, 14, 35], [], bt)
    with pytest.raises(SystemExit, match='超出范围'):
        _check(cfg, fd, ft, [], [1, 17])
