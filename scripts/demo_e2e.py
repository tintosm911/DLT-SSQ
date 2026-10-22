"""
端到端演示: 证明"完美预测"在数学上依然是负期望
================================================
思路: 取真实开奖号, 让工具评审这注号码.
  - 事后看: 中了一等奖
  - 事前算: 期望净收益 -0.94 元, 凯利 f*=0
两个彩种各跑一次 (DLT + SSQ).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.sqlite_storage import SQLiteStorage
from data.pick_advisor import Pick, PickAdvisor, get_game

SEP = '=' * 72


def demo(game: str):
    cfg = get_game(game)
    df = SQLiteStorage().load_dataframe(game)
    row = df.iloc[-1]

    actual = {
        'period': str(row['period']),
        'draw_date': str(row.get('draw_date', '')),
        'front': sorted(int(row[f'front_{i+1}']) for i in range(cfg.front_count)),
        'back': sorted(int(row[f'back_{i+1}']) for i in range(cfg.back_count)),
    }
    pick = Pick(front=actual['front'], back=actual['back'], label='真实开奖号')

    result = PickAdvisor(game).assess(
        pick,
        period=actual['period'],
        actual_draw=actual,
        recent_history=df.tail(300),
    )

    print()
    print(SEP)
    print(f"  {cfg.name} ({game.upper()})  第 {actual['period']} 期  {actual['draw_date']}")
    print(SEP)
    print(f"  真实开奖:   前 {actual['front']}  后 {actual['back']}")
    print()
    print('  --- 事后视角 (已开奖) ---')
    print(f"  命中奖级:   {result.hit_prize}")
    print(f"  中奖金额:   {result.win_money:,.0f} 元")
    print(f"  命中个数:   前 {result.hit_count.get('前区命中', 0)}/{cfg.front_count}"
          f"  后 {result.hit_count.get('后区命中', 0)}/{cfg.back_count}")
    print()
    print('  --- 事前视角 (开奖前你不知道结果) ---')
    print(f"  期望奖金:   {result.expected_prize:.4f} 元/注")
    print(f"  期望净收益: {result.expected_net:+.4f} 元/注   <-- 数学是负的")
    print(f"  凯利 f*:    {result.kelly_fraction:.3f}          <-- 公式说 [不投]")
    print(f"  一等奖概率: 1/{int(1 / result.first_prize_odds):,}")
    print()
    print('  --- 算法对"完美预测"的评分 (讽刺点) ---')
    if result.avg_score:
        scores = ' / '.join(f'{n}={result.avg_score.get(n, 50):.0f}'
                            for n in sorted(pick.front))
        print(f"  前区百分位: {scores}")
        if result.cold_nums:
            print(f"  冷号警告:   {result.cold_nums}  <-- 中奖的号被判为 [冷号]")
    return result


if __name__ == '__main__':
    print()
    print('  端到端演示: "完美预测" ≠ "正期望"')
    print('  工具的立场: 事前算清楚, 事后如实记录')

    dlt = demo('dlt')
    ssq = demo('ssq')

    print()
    print(SEP)
    print('  结论')
    print(SEP)
    print(f'  DLT 期望净收益: {dlt.expected_net:+.4f} 元/注  (中了 {dlt.win_money:,.0f} 元)')
    print(f'  SSQ 期望净收益: {ssq.expected_net:+.4f} 元/注  (中了 {ssq.win_money:,.0f} 元)')
    print()
    print('  中 500 万的那一注, 事前依然是"数学上该亏钱"的注.')
    print('  凯利 f*=0 永远成立, 无论你买哪一组号码.')
    print('  工具的价值不在预测, 在于诚实展示这件事.')
    print()