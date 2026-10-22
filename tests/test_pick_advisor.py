"""
pick_advisor 核心库的轻量测试
覆盖: 完美预测 / 生辰号 / JSON 序列化 / 无 recent_history
"""
import sys
from pathlib import Path

# 终端 GBK 编码保护
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.pick_advisor import (
    Pick, PickAdvisor, calc_expected_prize, judge_prize,
)


def test_calc_expected_prize_dlt():
    """DLT 期望净收益 -0.9407 元 (奖级表口径: 浮动奖取保底金额)"""
    p = Pick(front=[1, 2, 3, 4, 5], back=[1, 2])
    exp, net, kelly, prob_1 = calc_expected_prize('dlt', p)
    print(f'DLT: 期望={exp:.4f}, 净收益={net:+.4f}, kelly={kelly:.4f}, 一等奖 1/{int(1/prob_1):,}')
    # 期望值是确定量 (不是统计量), 直接断言精确值 —— 奖级表改动会立刻暴露
    assert abs(net + 0.9407) < 0.001, f'净收益应当是 -0.9407 元, 实际 {net}'
    assert abs(exp - 1.0593) < 0.001, f'期望奖金应当是 1.0593 元, 实际 {exp}'
    assert kelly == 0.0, '负期望 → kelly 必为 0'
    # 一等奖概率 = 1 / C(35,5)/C(12,2) ≈ 4.67e-08
    assert 4e-8 < prob_1 < 6e-8, f'一等奖 1/21425712, 实际 1/{int(1/prob_1):,}'


def test_calc_expected_prize_ssq():
    """SSQ 期望净收益 -0.8570 元"""
    p = Pick(front=list(range(1, 7)), back=[7])
    exp, net, kelly, prob_1 = calc_expected_prize('ssq', p)
    print(f'SSQ: 期望={exp:.4f}, 净收益={net:+.4f}, kelly={kelly:.4f}, 一等奖 1/{int(1/prob_1):,}')
    assert abs(net + 0.8570) < 0.001, f'净收益应当是 -0.8570 元, 实际 {net}'
    assert abs(exp - 1.1430) < 0.001, f'期望奖金应当是 1.1430 元, 实际 {exp}'
    assert kelly == 0.0
    # SSQ 一等奖 = 1 / C(33,6)/C(16,1) ≈ 5.99e-08
    assert 5e-8 < prob_1 < 7e-8


def test_judge_prize_dlt_perfect():
    """完美命中 DLT 一等奖"""
    p = Pick(front=[3, 6, 20, 24, 32], back=[4, 7])
    prize, money = judge_prize('dlt', p,
                               actual_front=[3, 6, 20, 24, 32],
                               actual_back=[4, 7])
    print(f'完美 DLT 命中: {prize} 奖金 {money:,}')
    assert prize == '一等奖'
    assert money == 5_000_000


def test_judge_prize_dlt_partial():
    """DLT 5+1 → 二等奖 30 万"""
    p = Pick(front=[3, 6, 20, 24, 32], back=[4, 7])
    prize, money = judge_prize('dlt', p,
                               actual_front=[3, 6, 20, 24, 32],
                               actual_back=[4, 9])
    print(f'5+1 DLT 命中: {prize} 奖金 {money:,}')
    assert prize == '二等奖'
    assert money == 300_000


def test_judge_prize_ssq_sixth():
    """SSQ 六等奖 (中 0+1) = 5 元"""
    p = Pick(front=[1, 2, 3, 4, 5, 6], back=[1])
    prize, money = judge_prize('ssq', p,
                               actual_front=[10, 20, 30, 31, 32, 33],
                               actual_back=[1])
    print(f'SSQ 0+1: {prize} 奖金 {money}')
    assert prize == '六等奖'
    assert money == 5


def test_birthday_pick_assess():
    """生辰号 (01-12 范围) 评估 → 期望净收益仍 < 0"""
    advisor = PickAdvisor('dlt')
    p = Pick(front=[1, 2, 3, 4, 5], back=[6, 12], label='生辰号测试')
    result = advisor.assess(p)
    print(f'生辰号: {result.verdict_label} | '
          f'期望 {result.expected_net:+.3f} | '
          f'建议 {result.recommendation} | '
          f'warnings={len(result.risk_warnings)}')
    assert result.expected_net < 0
    assert result.kelly_fraction == 0.0


def test_assess_to_json_roundtrip():
    """Assessor 输出可 JSON 序列化"""
    import json
    advisor = PickAdvisor('dlt')
    p = Pick(front=[3, 6, 20, 24, 32], back=[4, 7])
    actual = {
        'period': '26119',
        'draw_date': '2026-04-19',
        'front': [3, 6, 20, 24, 32],
        'back': [4, 7],
    }
    result = advisor.assess(p, period='26119', actual_draw=actual)
    d = result.to_dict()
    s = json.dumps(d, ensure_ascii=False)
    print(f'to_json OK ({len(s)} 字符): {s[:200]}...')
    assert result.hit_prize == '一等奖'
    assert result.win_money == 5_000_000
    # 验证 JSON 序列化无异常
    parsed = json.loads(s)
    assert parsed['pick']['front'] == [3, 6, 20, 24, 32]


def test_assess_no_history():
    """无 recent_history (只算期望)"""
    advisor = PickAdvisor('ssq')
    p = Pick(front=list(range(1, 7)), back=[7], label='纯期望评估')
    result = advisor.assess(p)
    print(f'无历史: 期望 {result.expected_net:+.3f}, '
          f'hot={result.hot_nums}, cold={result.cold_nums}, '
          f'algo_scores={"空" if not result.algo_scores else "有"}')
    assert result.expected_net < 0
    assert result.algo_scores == {} or result.algo_scores == {}


if __name__ == '__main__':
    fns = [v for k, v in globals().items() if k.startswith('test_')]
    fail = 0
    for fn in fns:
        try:
            print(f'\n=== {fn.__name__} ===')
            fn()
        except AssertionError as e:
            fail += 1
            print(f'  [FAIL] {e}')
        except Exception as e:
            fail += 1
            print(f'  [ERROR] {type(e).__name__}: {e}')
    total = len(fns)
    print(f'\n--- {total - fail}/{total} passed ---')
    sys.exit(fail)
