"""
奖级判定一致性检查
====================
对比两个来源:
  A. data/pick_advisor.py::judge_prize  (逐个条件硬编码)
  B. data/games.py::PRIZE_RULES          (奖级表)

任何不一致都会导致:
  - 期望值算错 (calc_expected_prize 用 B)
  - 模拟中奖率算错 (向量化 lookup 用 B)
  - 历史回测判奖错 (回测用 A)

用法:
  python scripts/check_prize_consistency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import get_game, get_prize_rules
from data.pick_advisor import Pick, judge_prize


def main():
    bad = 0
    for game in ('dlt', 'ssq'):
        cfg = get_game(game)
        rules = get_prize_rules(game)
        table = {}
        for cond, info in rules:
            label = info[0]
            money = info[1] if isinstance(info, (tuple, list)) and len(info) > 1 else 0
            table[(cond[0], cond[1])] = (label, money)

        print()
        print('=' * 72)
        print(f'  {cfg.name} ({game}) 奖级一致性检查')
        print('=' * 72)

        # 1. 遍历所有可能的前/后命中组合
        print(f'  {"前+后":<10}{"judge_prize":<22}{"PRIZE_RULES":<22}{"一致?"}')
        for nf in range(cfg.front_count + 1):
            for nb in range(cfg.back_count + 1):
                # 构造: 买的号 (1..n) + 开的号 (1..n 命中 + 后面不命中)
                front = list(range(1, cfg.front_count + 1))
                actual_front = list(range(1, nf + 1)) + \
                    list(range(cfg.front_count + 1,
                              cfg.front_count + (cfg.front_count - nf) + 1))
                back = list(range(1, cfg.back_count + 1))
                actual_back = list(range(1, nb + 1)) + \
                    list(range(cfg.back_count + 1,
                              cfg.back_count + (cfg.back_count - nb) + 1))
                if (len(actual_front) != cfg.front_count
                        or len(actual_back) != cfg.back_count):
                    continue
                label_a, money_a = judge_prize(
                    game, Pick(front=front, back=back),
                    actual_front, actual_back)
                got = table.get((nf, nb))
                if got is None:
                    # judge_prize 判未中 且 金额为 0 → 奖级表不列该组合属正常
                    if money_a == 0:
                        print(f'  {f"{nf}+{nb}":<10}{f"{label_a}/{money_a}元":<22}'
                              f'{"[未设奖级]":<22}✅')
                        continue
                    print(f'  {f"{nf}+{nb}":<10}{f"{label_a}/{money_a}元":<22}'
                          f'{"[缺失]":<22}❌ 缺失')
                    bad += 1
                    continue
                label_b, money_b = got
                if money_a == money_b and label_a == label_b:
                    mark = '✅'
                elif money_a == money_b:
                    mark = '⚠️名称'
                    bad += 1
                else:
                    mark = '❌金额'
                    bad += 1
                print(f'  {f"{nf}+{nb}":<10}{f"{label_a}/{money_a}元":<22}'
                      f'{f"{label_b}/{money_b}元":<22}{mark}')

    print()
    print('=' * 72)
    if bad:
        print(f'  ❌ 发现 {bad} 处不一致 — 期望值/模拟/回测都会受影响')
    else:
        print('  ✅ 完全一致')
    print('=' * 72)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main() or 0)
