"""
胆拖方案最终对比 (统一口径)
===========================
固定号码池下, 把常见胆拖结构放在**同一张表**里对比, 全部用精确超几何计算。

指标口径 (均为"至少中一注"的概率):
  中奖率  = 任意奖级
  ≥1万    = 三等奖及以上
  ≥3000   = 四等奖及以上
  ≥300    = 五等奖及以上

★ 唯一能在结构之间改变的变量就是"胆码个数"。
  具体选哪几个号做胆, 对中奖率**零影响** (开奖对称性, 见
  data/dan_tuo_exact.py 里的推导与 tests/test_dan_tuo_exact.py::t3)。

用法:
  python scripts/dantuo_final_compare.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from data.dan_tuo_exact import exact_dan_tuo

FP = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32, 35]
BP = [2, 4, 6, 9, 12]

SCHEMES = [
    ('A  原方案(你的)', [6], [x for x in FP if x != 6], [4], [x for x in BP if x != 4]),
    ('B  同预算·去后区胆', [2, 4], [x for x in FP if x not in (2, 4)], [], list(BP)),
    ('C  追热号·两胆', [32, 35], [x for x in FP if x not in (32, 35)], [12], [x for x in BP if x != 12]),
    ('D  双区零胆全覆盖', [], list(FP), [], list(BP)),
    ('E  省钱版', [6], [2, 4, 10, 14, 16, 18], [4], [2, 6, 9]),
    ('F  后区零胆·前区1胆', [6], [x for x in FP if x != 6], [], list(BP)),
    ('G  后区2胆·前区零胆', [], list(FP), [4, 12], [2, 6, 9]),
]

print()
print('=' * 112)
print('  胆拖方案最终对比 (全部精确超几何, 大乐透, 号码池 前区11 / 后区5)')
print('=' * 112)
print()
hdr = (f'  {"方案":<24}{"注数":>7}{"花费":>8}{"期望净收益":>12}{"中奖率":>9}'
       f'{"≥1万":>9}{"≥3000":>9}{"≥300":>9}{"全灭":>9}')
print(hdr)
print('  ' + '-' * 106)
rows = []
for label, fd, ft, bd, bt in SCHEMES:
    r = exact_dan_tuo('dlt', fd, ft, bd, bt)
    p1w = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 10000) * 100
    p3k = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 3000) * 100
    p300 = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 300) * 100
    rows.append((label, r, p1w, p3k, p300))
    print(f'  {label:<24}{r["n_bets"]:>7,}{r["cost"]:>8,.0f}{r["expected_net"]:>+12,.0f}'
          f'{r["win_rate"]:>8.2f}%{p1w:>8.3f}%{p3k:>8.3f}%{p300:>8.3f}%'
          f'{r["lose_rate"]:>8.2f}%')
print('  ' + '-' * 106)
print()
for label, r, p1w, p3k, p300 in rows:
    print(f'  {label}')
    print(f'      前区 胆 {" ".join(f"{v:02d}" for v in r["front_dan"]) or "(无)"}'
          f'   拖 {" ".join(f"{v:02d}" for v in r["front_tuo"])}')
    print(f'      后区 胆 {" ".join(f"{v:02d}" for v in r["back_dan"]) or "(无)"}'
          f'   拖 {" ".join(f"{v:02d}" for v in r["back_tuo"])}')
print()
print('  口径: ≥1万=三等奖及以上 · ≥3000=四等奖及以上 · ≥300=五等奖及以上 (均为"至少中一注"的概率)')
print('  单注期望净收益全部 = -0.9407 元, 与结构无关。')
