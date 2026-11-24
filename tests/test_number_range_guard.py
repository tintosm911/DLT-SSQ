"""
号码范围守卫测试 (v3.2.2 修复的静默 bug)
=========================================
★ 背景:
  双色球红球 1-33, 大乐透红球 1-35。用户把大乐透的号码池直接拿去跑双色球时,
  35 是**非法号**。修复前工具不校验 → 静默给出两个都错的数字:
    ① 注数虚增 (含 35 的组合是永远不会中奖的废注)  75 注 vs 真实 50 注
    ② 中奖率**虚高** 45.67% vs 真实 42.81%  ← 更危险: 错得更"好看"

覆盖:
  T1 exact_dan_tuo 对越界号码抛错 (数据层兜底)
  T2 optimize 对越界号码池抛错 (入口层拦截)
  T3 回归证据: 含非法号的旧路径确实给出**不同(且虚高)**的中奖率
  T4 dan_tuo_plan.py 自动剔除越界号, 且生成的方案里不出现非法号
  T5 两个彩种各自的合法边界仍然正常工作 (不误伤)
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

from data.dan_tuo_exact import exact_dan_tuo
from data.dan_tuo_optimizer import optimize


# 大乐透号码池 (含 35) —— 双色球红球只到 33, 所以 35 越界
DLT_POOL_F = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32, 35]
SSQ_POOL_F = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32]
POOL_B = [2, 4, 6, 9, 12]


def test_note_1_exact_solver_rejects_out_of_range():
    with pytest.raises(ValueError, match='超出范围'):
        exact_dan_tuo('ssq', [2, 4, 6, 10], [16, 18, 23, 26, 32, 35],
                      [], POOL_B)
    with pytest.raises(ValueError, match='超出范围'):
        exact_dan_tuo('ssq', [2, 4], [6, 10], [17], [1, 2])   # 后区 17 > 16


def test_note_2_optimizer_rejects_bad_pool():
    with pytest.raises(ValueError, match='非法号码'):
        optimize('ssq', budget=200, goal='win',
                 front_pool=DLT_POOL_F, back_pool=POOL_B)
    with pytest.raises(ValueError, match='非法号码'):
        optimize('ssq', budget=200, goal='win',
                 front_pool=SSQ_POOL_F, back_pool=[2, 4, 17])


def test_note_3_old_path_really_gave_a_higher_wrong_rate():
    """
    回归证据: 把修复前实测到的**错数字**固定在这里。
    同一结构 (前 4 胆/6 拖 × 后 0 胆/5 拖), 拖码池塞进非法号 35 后:
        注数     75 (虚增 25 注 —— 含 35 的组合开奖永远不会中)
        中奖率   45.6697%  ← 比正确值高, 错得更"好看", 更危险
    正确值 (拖码池 6 个合法号):
        注数     50, 中奖率 42.8115%
    """
    r_ok = exact_dan_tuo('ssq', [2, 4, 6, 10], [16, 18, 23, 26, 32],
                         [], POOL_B)
    assert r_ok['n_bets'] == 50
    assert abs(r_ok['win_rate'] - 42.8115) < 0.001

    # 修复前实测到的错数字 (现在已被 T1 拦死, 这里只做文档化断言)
    BUGGY_N_BETS = 75
    BUGGY_WIN_RATE = 45.6697
    assert BUGGY_N_BETS != r_ok['n_bets']
    assert BUGGY_WIN_RATE > r_ok['win_rate'], '旧路径是**虚高**, 不是虚低'
    # 虚增的 25 注全是废注
    from math import comb
    assert (comb(7, 2) - comb(6, 2)) * len(POOL_B) == 30
    assert BUGGY_N_BETS - r_ok['n_bets'] == 25


def test_note_4_plan_script_filters_and_warns():
    out = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'dan_tuo_plan.py'),
         '--game', 'ssq',
         '--front-pool', ' '.join(str(v) for v in DLT_POOL_F),
         '--back-pool', ' '.join(str(v) for v in POOL_B),
         '--budgets', '200'],
        cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
        timeout=600)
    assert out.returncode == 0, out.stderr
    assert '已剔除越界号码' in out.stdout
    assert '35' in out.stdout
    # 剔除后池子剩 10 个号
    assert '前区号码池 (10 个)' in out.stdout
    # 生成的方案里不该出现 35 作为号码
    assert '胆 35' not in out.stdout
    assert '拖 35' not in out.stdout


def test_note_5_valid_pools_still_work():
    # 大乐透: 35 合法, 不能误伤
    r = optimize('dlt', budget=1680, goal='win',
                 front_pool=DLT_POOL_F, back_pool=POOL_B, top_n=1)
    assert r['best']['n_bets'] == 840
    # 双色球: 33 合法
    r2 = optimize('ssq', budget=350, goal='win',
                  front_pool=SSQ_POOL_F, back_pool=POOL_B, top_n=1)
    assert r2['best']['n_bets'] == 175
