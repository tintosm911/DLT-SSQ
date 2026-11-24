"""
胆拖投注规则校验测试 (v3.2.7)
================================
★ 背景:
  此前工具**不知道"胆码有上限"**, 于是会生成"大乐透前区 5 胆"这种
  彩票店根本不出票的结构 —— 用户拿去买会被退, 而且数字还长得挺漂亮。

覆盖:
  T1 大乐透前区胆码 ≤ 4 (5 胆必须被拒)
  T2 大乐透后区胆码 ≤ 1 (2 胆必须被拒)
  T3 大乐透后区 1 胆时拖码 ≥ 2 (1胆1拖 = 单式, 不是胆拖)
  T4 大乐透前区有胆时胆+拖 ≥ 6
  T5 双色球红球胆码 ≤ 5, 蓝球不许设胆码
  T6 双色球红球有胆时胆+拖 ≥ 7
  T7 优化器**只产出合法结构** (k ≤ 4 / m ≤ 1)
  T8 展开器拒绝非法结构
  T9 合法结构照常工作 (不误伤)
"""
import subprocess
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

from data.dan_tuo_exact import check_dan_tuo_rules, exact_dan_tuo
from data.dan_tuo_optimizer import optimize
from data.games import get_game


def test_note_1_dlt_front_dan_max_4():
    # 前 5 胆 → 非法
    problems = check_dan_tuo_rules('dlt', [1, 2, 3, 4, 5], [6, 7],
                                   [], [1, 2])
    assert any('胆码 5 个超过上限 4 个' in p for p in problems)
    with pytest.raises(ValueError, match='胆拖投注规则'):
        exact_dan_tuo('dlt', [1, 2, 3, 4, 5], [6, 7], [], [1, 2])
    # 前 4 胆 → 合法
    assert check_dan_tuo_rules('dlt', [1, 2, 3, 4], [6, 7], [], [1, 2]) == []


def test_note_2_dlt_back_dan_max_1():
    problems = check_dan_tuo_rules('dlt', [1, 2], [3, 4, 5], [1, 2], [3, 4])
    assert any('后区胆码 2 个超过上限 1 个' in p for p in problems)
    with pytest.raises(ValueError, match='胆拖投注规则'):
        exact_dan_tuo('dlt', [1, 2], [3, 4, 5], [1, 2], [3, 4])


def test_note_3_dlt_back_1dan_needs_2tuo():
    # 1 胆 + 1 拖 = 后区固定 2 个 → 是单式, 不是胆拖
    problems = check_dan_tuo_rules('dlt', [1, 2, 3, 4], [5, 6, 7], [1], [2])
    assert any('不构成胆拖' in p for p in problems)
    # 1 胆 + 2 拖 → 合法
    assert check_dan_tuo_rules('dlt', [1, 2, 3, 4], [5, 6, 7], [1], [2, 3]) == []


def test_note_4_dlt_front_dan_plus_tuo_min_6():
    # 前 1 胆 + 4 拖 = 5 个 → 凑不出多注, 实质单式
    problems = check_dan_tuo_rules('dlt', [1], [2, 3, 4, 5], [], [1, 2])
    assert any('不构成胆拖' in p for p in problems)
    assert check_dan_tuo_rules('dlt', [1], [2, 3, 4, 5, 6], [], [1, 2]) == []


def test_note_5_ssq_rules():
    # 红球 6 胆 → 超过上限 5
    problems = check_dan_tuo_rules('ssq', [1, 2, 3, 4, 5, 6], [7, 8],
                                   [], [1])
    assert any('超过上限 5 个' in p for p in problems)
    # ★ 蓝球不许设胆码
    problems2 = check_dan_tuo_rules('ssq', [1, 2, 3], [4, 5, 6, 7], [3], [1, 2])
    assert any('超过上限 0 个' in p for p in problems2)
    with pytest.raises(ValueError, match='胆拖投注规则'):
        exact_dan_tuo('ssq', [1, 2, 3], [4, 5, 6, 7], [3], [1, 2])


def test_note_6_ssq_front_dan_plus_tuo_min_7():
    # 红 5 胆 + 1 拖 = 6 个 → 实质单式, 非法
    problems = check_dan_tuo_rules('ssq', [1, 2, 3, 4, 5], [6], [], [1])
    assert any('不构成胆拖' in p for p in problems)
    assert check_dan_tuo_rules('ssq', [1, 2, 3, 4, 5], [6, 7], [], [1]) == []


def test_note_7_optimizer_only_outputs_legal_structures():
    for game, pool_f, pool_b in (
            ('dlt', [2, 3, 4, 6, 10, 11, 12, 22, 23, 26, 27, 32],
             [2, 4, 5, 6, 7, 8, 9, 10, 12]),
            ('ssq', [30, 4, 14, 13, 22, 26, 5, 10, 20, 6],
             [11, 12, 4, 14, 2])):
        cfg = get_game(game)
        for budget in (20, 60, 100, 350, 1680):
            for goal in ('win', 'big'):
                r = optimize(game, budget=budget, goal=goal,
                             front_pool=pool_f, back_pool=pool_b, top_n=5)
                for cand in r['candidates']:
                    assert cand['k'] <= cfg.front_max_dan, \
                        f'{game} 产出了 {cand["k"]} 胆的非法结构'
                    assert cand['m'] <= cfg.back_max_dan, \
                        f'{game} 产出了 {cand["m"]} 后区胆的非法结构'
                    assert check_dan_tuo_rules(
                        game, cand['front_dan'], cand['front_tuo'],
                        cand['back_dan'], cand['back_tuo']) == [], \
                        f'{game} 产出非法结构: {cand["structure"]}'


def test_note_8_expander_rejects_illegal():
    out = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'expand_dan_tuo.py'),
         '--game', 'dlt',
         '--front-dan', '1 2 3 4 5', '--front-tuo', '6 7',
         '--back-tuo', '1 2'],
        cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
        timeout=120)
    assert out.returncode != 0
    assert '超过上限' in (out.stdout + out.stderr)


def test_note_9_legal_structures_still_work():
    # 方案 A: 前 3 胆/7 拖 × 后 1 胆/4 拖 = 84 注
    r = exact_dan_tuo('dlt', [2, 4, 6], [10, 14, 16, 18, 23, 26, 32],
                      [2], [4, 6, 9, 12])
    assert r['n_bets'] == 84
    # 双色球 5 胆 2 拖 × 蓝球 1 个 = 2 注
    r2 = exact_dan_tuo('ssq', [1, 2, 3, 4, 5], [6, 7], [], [1])
    assert r2['n_bets'] == 2
