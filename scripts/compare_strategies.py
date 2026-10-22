"""策略对比: 各奖级命中次数拆解 (证明策略有效在哪)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.strategy_lab import run_lab

r = run_lab('dlt', window=200, start=500, n_seeds=3)
d = {s['name']: s for s in r['strategies']}
names = ['random', 'odd_even', 'repeat_last', 'hot', 'cold']
labels = sorted({l for n in names for l, _ in d[n]['prizes']},
                key=lambda l: -sum(dict(d[n]['prizes']).get(l, 0) for n in names))

print()
print(f'各策略奖级命中次数 ({r["tested_draws"]} 期回测, 每期 1 注)')
print()
print(f'{"奖级":<10}' + ''.join(f'{n:>14}' for n in names))
print('-' * (10 + 14 * len(names)))
for l in labels:
    row = ''.join(f'{dict(d[n]["prizes"]).get(l, 0):>14}' for n in names)
    print(f'{l:<10}' + row)
print('-' * (10 + 14 * len(names)))
for key, fmt in (('中奖次数', '{:>14}'), ('中奖率%', '{:>14.2f}'),
                  ('返奖元', '{:>14.0f}'), ('ROI%', '{:>14.2f}')):
    vals = []
    for n in names:
        v = d[n][key] if key in d[n] else d[n].get(
            'win_rate' if key == '中奖率%' else
            'returns' if key == '返奖元' else
            'roi' if key == 'ROI%' else 'wins', 0)
        vals.append(fmt.format(v))
    print(f'{key:<10}' + ''.join(vals))

print()
print('奖级期望概率 (每注):')
bd = r['payout_breakdown']
for x in sorted(bd['detail'], key=lambda x: -x['prob'])[:8]:
    print(f'   {x["label"]:<8} {x["money"]:>10,} 元   概率 {x["prob"]:.6f}  '
          f'期望贡献 {x["contrib"]:.4f} 元/注  '
          f'{"★大奖" if x["big"] else ""}')

print()
print(f'派奖率拆解: 总 {bd["total_payout"]:.2f}% = '
      f'大奖 {bd["big_payout"]:.2f}% + 小奖 {bd["small_payout"]:.2f}%')
print(f'  剔除大奖后的期望 ROI: {bd["roi_small_only"]:+.2f}%')
print()
print('结论:', r['conclusion'])
