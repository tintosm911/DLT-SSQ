"""
竞彩 vs 境外盘口 套利测算
==========================
用**真实历史赔率** + **实测的中国竞彩抽水率** (12.91%), 测算:
"如果中国竞彩的赔率水平出现在国际市场上, 跟境外公司能套出多少利润?"

方法:
  1. 从真实比赛里取市场最优概率 (各公司去水后取共识)
  2. 按竞彩抽水 12.91% 给这个概率定价 → 模拟"竞彩赔率"
  3. 枚举 (竞彩主/平/客) × (境外公司) 的组合, 找 Σ(1/odds) < 1
  4. 算资金回测 ROI

这是**用真实数据验证方法论**, 不依赖实时境外源.
"""
from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np

# 实测的中国竞彩抽水率 (2026-10-22, 24 场实时, data/jingcai_odds.py)
JINGCAI_VIG = 0.1291

# 境外独立公司 (只用这些做对手方)
OVERSEAS_BOOKS = ['B365', 'Pinnacle', 'WilliamHill', 'Betfair', 'VCBet',
                   'Interwetten', 'Ladbrokes']


def devig(odds: Tuple[float, float, float]) -> np.ndarray:
    """赔率 → 去水后的隐含概率 (市场共识)"""
    p = np.array([1.0 / o for o in odds])
    return p / p.sum()


def jingcai_odds(market_odds: Tuple[float, float, float],
                 vig: float = JINGCAI_VIG) -> Tuple[float, float, float]:
    """
    按"市场共识概率 × (1+vig)" 反推竞彩赔率.

    中国竞彩是固定奖金, 理论抽水由官方设定在 12.9% 左右 (实测).
    """
    p = devig(market_odds)
    return tuple(float(1.0 / (pi * (1.0 + vig))) for pi in p)


@dataclass
class Arb:
    date: str
    home: str
    away: str
    combo: Tuple[str, str, str]      # (主, 平, 客) 各来自哪边
    odds: Tuple[float, float, float]
    sum_inv: float
    profit: float                    # 锁定利润 %

    def stakes(self, total: float = 100.0):
        inv = [1.0 / o for o in self.odds]
        s = sum(inv)
        payout = total / s
        return [(c, payout / o, payout) for c, o in zip(self.combo, self.odds)]


def find_arbs_with_jingcai(matches: Sequence[Dict],
                            vig: float = JINGCAI_VIG,
                            min_profit: float = 0.0,
                            allow_jingcai: bool = True) -> List[Arb]:
    """
    对每场比赛:
      - 用市场共识概率 (取所有可用公司去水后平均) 反推"竞彩赔率"
      - 枚举 竞彩 + 1~2 家境外公司 的组合

    ⚠ 重要: 竞彩抽水 12.91% >> 境外 2.45%~8.00%,
      意味着竞彩赔率**更低**、隐含概率**更高**。
      所以"竞彩 + 境外"的组合 Σ(1/o) 更大 → **更难**套利。
      allow_jingcai=False 时才是纯境外组合 (对照组).
    """
    out = []
    for m in matches:
        avail = {b: m['odds'][b] for b in OVERSEAS_BOOKS if b in m.get('odds', {})}
        if len(avail) < 2:
            continue
        # 市场共识: 各公司去水概率的平均
        probs = np.mean([devig(o) for o in avail.values()], axis=0)
        jc = tuple(1.0 / (p * (1.0 + vig)) for p in probs)

        best = None
        # 三个结果各选一边: 竞彩(JC) 或 某家境外公司
        sides = list(avail.items())
        if allow_jingcai:
            sides = [('竞彩', jc)] + sides
        for combo in itertools.product(sides, repeat=3):
            (b1, o1), (b2, o2), (b3, o3) = combo
            # ⚠ 三个来源必须互不相同 —— 同一家公司同时出主胜和平局会算出假套利
            if b1 == b2 or b2 == b3 or b1 == b3:
                continue
            s = 1.0 / o1[0] + 1.0 / o2[1] + 1.0 / o3[2]
            if s < 1.0 - min_profit and (best is None or s < best[0]):
                best = (s, (b1, b2, b3), (o1[0], o2[1], o3[2]))
        if best:
            out.append(Arb(
                date=m.get('date', ''), home=m.get('home', ''),
                away=m.get('away', ''),
                combo=best[1], odds=best[2], sum_inv=best[0],
                profit=(1.0 / best[0] - 1.0) * 100))
    return out


def backtest(matches: Sequence[Dict], vig: float = JINGCAI_VIG,
             min_profit: float = 0.005, max_per_day: int = 5,
             stake: float = 100.0,
             allow_jingcai: bool = True) -> Dict:
    """资金回测"""
    arbs = find_arbs_with_jingcai(matches, vig, min_profit, allow_jingcai)
    if not arbs:
        return {'count': 0, 'matches': len(matches), 'rate': 0.0}

    by_day: Dict[str, List[Arb]] = {}
    for a in arbs:
        by_day.setdefault(a.date, []).append(a)

    total_stake = 0.0
    total_return = 0.0
    n = 0
    profits = []
    for day, items in by_day.items():
        items.sort(key=lambda x: -x.profit)
        for a in items[:max_per_day]:
            plan = a.stakes(stake)
            total_stake += sum(s for _, s, _ in plan)
            total_return += plan[0][2]
            profits.append(a.profit)
            n += 1
    net = total_return - total_stake
    return {
        'count': n,
        'found': len(arbs),
        'matches': len(matches),
        'rate': len(arbs) / len(matches) * 100,
        'stake': total_stake,
        'returns': total_return,
        'net': net,
        'roi': net / total_stake * 100 if total_stake else 0,
        'avg_profit': float(np.mean(profits)),
        'max_profit': max(profits),
        'arbs': arbs,
    }


def main():
    from data.sports_odds import parse_season, CACHE_DIR
    from data.sports_arb import analyze_vig

    files = sorted(CACHE_DIR.glob('premier-league_*.csv'))
    ms = []
    for f in files:
        ms.extend(parse_season(f.read_text(encoding='utf-8-sig')))

    print('=' * 76)
    print('  竞彩 vs 境外盘口 套利测算')
    print('=' * 76)
    print(f'  真实历史赔率: {len(ms)} 场 (英超)')
    print(f'  竞彩抽水率:   {JINGCAI_VIG*100:.2f}% (2026-10-22 实测 24 场)')

    vig = analyze_vig(ms)
    print()
    print('  【1】境外各公司抽水率 (对照)')
    for k, v in sorted(vig.items(), key=lambda x: x[1]['mean']):
        if k in OVERSEAS_BOOKS:
            print(f'      {k:<14}{v["mean"]*100:>8.2f}%')
    best_ov = min((v['mean'] for k, v in vig.items() if k in OVERSEAS_BOOKS),
                   default=0)
    print(f'      境外最低抽水 {best_ov*100:.2f}%  vs  竞彩 {JINGCAI_VIG*100:.2f}%')
    print(f'      → 价差 {(JINGCAI_VIG-best_ov)*100:.2f} 个百分点 (套利的空间来源)')

    print()
    print('  【2】套利机会扫描: 纯境外 vs 含竞彩')
    print(f'      {"组合类型":<20}{"可套利场次":>12}{"占比":>9}{"资金ROI":>11}')
    for label, allow in (('纯境外公司', False), ('含竞彩的组合', True)):
        b = backtest(ms, JINGCAI_VIG, min_profit=0.005, allow_jingcai=allow)
        roi = b['roi'] if b.get('count') else 0
        rate = b.get('rate', 0)
        print(f'      {label:<20}{b.get("found", 0):>12}{rate:>8.2f}%{roi:>10.3f}%')
    print()
    print('      → 反直觉结论: **竞彩的高抽水不是套利机会, 而是套利障碍**')
    print('        竞彩赔率更低 → 隐含概率更高 → 用它下注会拉高 Σ(1/o),')
    print('        反而让"竞彩+境外"的组合更难满足 Σ<1.')

    bt = backtest(ms, JINGCAI_VIG, min_profit=0.005, allow_jingcai=True)
    if bt.get('arbs'):
        n_jc = sum(1 for a in bt['arbs'] if '竞彩' in a.combo)
        print()
        print(f'  【3】含竞彩的 {bt["found"]} 场套利中, 有 {n_jc} 场真的用到了竞彩')
        if bt['arbs']:
            best = max(bt['arbs'], key=lambda a: a.profit)
            print(f'      最佳: {best.date} {best.home} vs {best.away}')
            print(f'        组合: 主 {best.combo[0]} / 平 {best.combo[1]} / 客 {best.combo[2]}')
            print(f'        Σ(1/o) = {best.sum_inv:.6f} → 锁定 {best.profit:.3f}%')
            for book, st, ret in best.stakes(100):
                tag = ' [竞彩]' if book == '竞彩' else ''
                print(f'          {book:<14}{tag:<8} 投入 {st:>6.2f} 元  (中则返 {ret:.2f})')

    print()
    print('  【4】竞彩抽水率 vs 套利空间 (纯境外组合, 对照组)')
    print(f'      {"竞彩抽水":>10}{"纯境外可套利%":>16}{"含竞彩可套利%":>16}')
    for v in (0.05, 0.10, 0.1291, 0.15, 0.20):
        b0 = backtest(ms, v, min_profit=0.005, allow_jingcai=False)
        b1 = backtest(ms, v, min_profit=0.005, allow_jingcai=True)
        print(f'      {v*100:>9.2f}%{b0.get("rate", 0):>15.2f}%{b1.get("rate", 0):>15.2f}%')
    print()
    print('  说明: 纯境外组合的套利率跟竞彩抽水无关 (竞彩不在组合里);')
    print('        竞彩抽水越高, "含竞彩"的组合越难套利.')
    print('=' * 76)


if __name__ == '__main__':
    main()
