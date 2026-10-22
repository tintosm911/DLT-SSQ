"""
竞彩期望值分析器
================
回答一个跟号码彩完全不同的问题:
**竞彩的期望值能不能是正的?**

三个层次 (从确定到不确定):
  1. **抽水 (vig)** — 赔率隐含概率之和 > 1, 超额部分 = 庄家优势
     这是"必输"的部分: Σ(1/odds) > 1 意味着无条件下注必然亏
  2. **跨公司套利 (arb)** — 同场不同公司组合, 若 Σ(1/odds) < 1 则锁定利润
     这是**数学上必赢**的场景 (前提: 能真的在各公司下到注)
  3. **价值下注 (value bet)** — 用 Elo 模型估概率, 对比赔率隐含概率
     找正期望的注, 再用凯利公式定仓位
     这是**统计套利**, 长期能否盈利取决于模型是否真比市场准

所有分析都用**真实历史赔率** (football-data.co.uk 镜像), 非模拟数据。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ============================================================
# 1. 抽水分析
# ============================================================
def implied_probabilities(odds: Tuple[float, float, float]) -> np.ndarray:
    """欧式赔率 → 隐含概率 (未去水)"""
    return np.array([1.0 / o for o in odds])


def devig(probs: np.ndarray) -> np.ndarray:
    """去除抽水 (比例归一化)"""
    s = probs.sum()
    return probs / s if s > 0 else probs


def vig(odds: Tuple[float, float, float]) -> float:
    """抽水率 = Σ(1/odds) - 1"""
    return float(implied_probabilities(odds).sum() - 1.0)


def analyze_vig(matches: Sequence[Dict]) -> Dict:
    """各博彩公司的抽水率统计"""
    stats: Dict[str, List[float]] = {}
    for m in matches:
        for name, o in m.get('odds', {}).items():
            stats.setdefault(name, []).append(vig(o))
    out = {}
    for name, vs in stats.items():
        if len(vs) < 20:
            continue
        arr = np.array(vs)
        out[name] = {
            'count': len(vs),
            'mean': float(arr.mean()),
            'median': float(np.median(arr)),
            'min': float(arr.min()),
            'max': float(arr.max()),
            'std': float(arr.std()),
            'p10': float(np.percentile(arr, 10)),
            'p90': float(np.percentile(arr, 90)),
        }
    return out


# ============================================================
# 2. 跨公司套利
# ============================================================
@dataclass
class ArbOpportunity:
    match_idx: int
    date: str
    home: str
    away: str
    books: Tuple[str, str, str]      # (主, 平, 客) 各用哪家公司
    odds: Tuple[float, float, float]
    sum_inv: float                   # Σ(1/odds)
    profit_pct: float                # 锁定利润 %

    def stake_plan(self, total: float = 100.0) -> List[Tuple[str, float, float]]:
        """
        按比例分配本金 (三注回报相等, 无论哪注中奖都拿同样的钱).

        stake_i = R / o_i,  总投入 = R × Σ(1/o_i) = R × s
        → R = total / s,  每注回报都是 R
        ⚠ 关键: 只有**中注的那一注**实际返还, 其余注打水漂,
          所以总回报是 R 而不是 3R.
        """
        inv = [1.0 / o for o in self.odds]
        s = sum(inv)
        payout = total / s          # 无论哪注中, 都拿这个数
        out = []
        for book, o in zip(self.books, self.odds):
            stake = payout / o
            out.append((book, stake, payout))
        return out

    @property
    def total_stake(self) -> float:
        """下注总额 (等于 stake_plan 的 total)"""
        inv = [1.0 / o for o in self.odds]
        s = sum(inv)
        return sum((1.0 / s) / o for o in self.odds)


def find_arbs(matches: Sequence[Dict], books: Sequence[str],
              min_profit: float = 0.0, max_arb_books: int = 3) -> List[ArbOpportunity]:
    """
    找跨公司套利.

    对每场比赛, 枚举"主/平/客 各选一家不同公司"的所有组合,
    若 Σ(1/odds) < 1 则存在套利, 利润 = 1/Σ - 1.
    """
    out = []
    for i, m in enumerate(matches):
        avail = [(b, m['odds'][b]) for b in books if b in m.get('odds', {})]
        if len(avail) < 2:
            continue
        best = None
        # 允许同一公司出两个结果 (罕见但会破坏套利), 这里强制三家互不相同
        for combo in itertools.permutations(avail, 3):
            (bh, oh), (bd, od), (ba, oa) = combo
            if bh == bd or bd == ba or bh == ba:
                continue
            s = 1.0 / oh[0] + 1.0 / od[1] + 1.0 / oa[2]
            if s < 1.0 - min_profit and (best is None or s < best[0]):
                best = (s, bh, bd, ba, oh[0], od[1], oa[2])
        if best:
            s = best[0]
            out.append(ArbOpportunity(
                match_idx=i,
                date=m.get('date', ''),
                home=m.get('home', ''),
                away=m.get('away', ''),
                books=(best[1], best[2], best[3]),
                odds=(best[4], best[5], best[6]),
                sum_inv=s,
                profit_pct=(1.0 / s - 1.0) * 100,
            ))
    return out


def analyze_arb(matches: Sequence[Dict], books: Sequence[str],
                min_profit: float = 0.0) -> Dict:
    """套利机会统计"""
    arbs = find_arbs(matches, books, min_profit=min_profit)
    checked = sum(1 for m in matches
                  if len([b for b in books if b in m.get('odds', {})]) >= 3)
    if not arbs:
        return {
            'count': 0, 'checked': checked, 'rate': 0.0,
            'max_profit': 0.0, 'mean_profit': 0.0,
            'best': None, 'arbs': [],
        }
    profits = [a.profit_pct for a in arbs]
    return {
        'count': len(arbs),
        'checked': checked,
        'rate': len(arbs) / checked * 100 if checked else 0.0,
        'max_profit': max(profits),
        'mean_profit': float(np.mean(profits)),
        'median_profit': float(np.median(profits)),
        'best': max(arbs, key=lambda a: a.profit_pct),
        'arbs': arbs,
    }


# ============================================================
# 3. 套利资金回测 (真实投钱会怎样)
# ============================================================
def backtest_arbs(matches: Sequence[Dict], books: Sequence[str],
                   min_profit: float = 0.005,
                   stake_per_arb: float = 100.0,
                   max_stakes_per_day: int = 5,
                   verbose: bool = False) -> Dict:
    """
    套利资金回测.

    每场都检查是否存在套利; 有则按比例分配 stake_per_arb 元下注 (锁定利润).
    计入实际摩擦:
      - 单场最多下注几次 (一天几十场, 不可能全抓)
      - 分散到各公司的注额都算 (真实要 3 个账户)
    """
    arbs = find_arbs(matches, books, min_profit=min_profit)
    if not arbs:
        return {'count': 0, 'stake': 0, 'returns': 0, 'net': 0, 'roi': 0,
                'matches': 0, 'avg_profit': 0}

    # 按日期分组, 每天最多 max_stakes_per_day 次
    by_day: Dict[str, List[ArbOpportunity]] = {}
    for a in arbs:
        by_day.setdefault(a.date, []).append(a)

    total_stake = 0.0
    total_return = 0.0
    n_taken = 0
    taken_profits = []
    for day, items in by_day.items():
        items.sort(key=lambda x: -x.profit_pct)
        for a in items[:max_stakes_per_day]:
            plan = a.stake_plan(stake_per_arb)
            # 三注都下, 只有中注的那注返还 → 总回报 = 单注回报 (不是三注之和)
            total_stake += sum(stake for _, stake, _ in plan)
            total_return += plan[0][2]
            taken_profits.append(a.profit_pct)
            n_taken += 1

    net = total_return - total_stake
    return {
        'count': n_taken,
        'found': len(arbs),
        'matches': len(matches),
        'stake': total_stake,
        'returns': total_return,
        'net': net,
        'roi': net / total_stake * 100 if total_stake else 0,
        'avg_profit': float(np.mean(taken_profits)) if taken_profits else 0,
        'max_stakes_per_day': max_stakes_per_day,
    }


# ============================================================
# 4. Elo 模型 + 价值下注
# ============================================================
class EloModel:
    """
    Elo 评分系统 (含主场优势 + 时间衰减).

    只用**过去**的比赛更新, 预测未来 —— 严格 walk-forward.

    时间衰减: 每场比赛把双方评分向均值拉回 (衰减系数 decay),
    避免十年前的强队评分永远影响今天.
    """

    def __init__(self, k: float = 20.0, home_adv: float = 60.0,
                 decay: float = 0.002, mean: float = 1500.0):
        self.k = k
        self.home_adv = home_adv
        self.decay = decay
        self.mean = mean
        self.ratings: Dict[str, float] = {}

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.mean)

    def _draw_prob(self, eh: float) -> float:
        """经验公式: 实力接近时平局概率更高"""
        return max(0.12, min(0.34, 0.26 - 0.14 * abs(eh - 0.5)))

    def expected(self, home: str, away: str) -> Tuple[float, float, float]:
        """返回 (主胜, 平, 客胜) 的真实概率估计"""
        rh = self.rating(home) + self.home_adv
        ra = self.rating(away)
        eh = 1.0 / (1.0 + 10 ** ((ra - rh) / 400.0))
        draw = self._draw_prob(eh)
        eh = (eh - draw) / max(1e-9, 1 - draw)
        ea = (1.0 - draw) - eh
        return eh, draw, ea

    def update(self, home: str, away: str, ftr: str) -> None:
        rh = self.rating(home)
        ra = self.rating(away)
        eh = 1.0 / (1.0 + 10 ** ((ra - rh - self.home_adv) / 400.0))
        draw = self._draw_prob(eh)
        eh = (eh - draw) / max(1e-9, 1 - draw)
        ea = (1.0 - draw) - eh
        score = {'H': 1.0, 'D': 0.5, 'A': 0.0}[ftr]
        exp = {'H': eh, 'D': draw, 'A': ea}[ftr]
        self.ratings[home] = rh + self.k * (score - exp)
        self.ratings[away] = ra + self.k * ((1 - score) - (1 - exp))
        # 时间衰减: 向均值拉回
        if self.decay > 0:
            for t in (home, away):
                self.ratings[t] = self.mean + (
                    self.ratings[t] - self.mean) * (1 - self.decay)


@dataclass
class ValueBetResult:
    bets: int = 0
    wins: int = 0
    stake: float = 0.0
    returns: float = 0.0
    roi: float = 0.0
    clv: float = 0.0            # 收盘线价值 (Closing Line Value)
    max_drawdown: float = 0.0
    kelly_bets: int = 0
    equity: List[float] = field(default_factory=list)
    hit_rate: float = 0.0
    edge_hist: List[float] = field(default_factory=list)


def backtest_value_bets(matches: Sequence[Dict], book: str = 'Pinnacle',
                         edge_threshold: float = 0.03,
                         kelly_fraction: float = 0.25,
                         use_kelly: bool = True,
                         closing_book: str = 'Pinnacle_C') -> ValueBetResult:
    """
    严格 walk-forward 价值下注回测.

    每场比赛:
      1. 用**之前**的比赛更新 Elo
      2. 用 Elo 概率 vs 该博彩公司赔率隐含概率, 找 value
      3. edge > 阈值 → 下注 (凯利仓位或固定仓位)
      4. 用赛果结算
      5. 记录收盘线价值 (CLV): 收盘赔率隐含概率 vs 下注时隐含概率
    """
    res = ValueBetResult()
    elo = EloModel()
    equity = 0.0
    peak = 0.0

    for m in matches:
        odds = m.get('odds', {}).get(book)
        if odds is None:
            elo.update(m['home'], m['away'], m['ftr'])
            continue

        probs = elo.expected(m['home'], m['away'])
        # ⚠ 必须用**去水后**的隐含概率作为市场基准.
        #   原始 1/odds 含 vig (B365 约 5.5%), 会让所有 edge 系统性虚高,
        #   导致去下一堆"其实没优势"的注.
        implied = devig(implied_probabilities(odds))

        for idx, outcome in enumerate(('H', 'D', 'A')):
            p = probs[idx]
            q = implied[idx]
            edge = p - q
            if edge <= edge_threshold:
                continue
            o = odds[idx]
            # 凯利仓位: f* = (b*p - q) / b, b = o - 1
            b = o - 1.0
            kelly = ((b * p - q) / b) if b > 0 else 0.0
            kelly = max(0.0, min(1.0, kelly))
            frac = kelly * kelly_fraction if use_kelly else 1.0

            res.bets += 1
            res.stake += frac
            won = (m['ftr'] == outcome)
            if won:
                res.wins += 1
                res.returns += frac * o
            res.edge_hist.append(edge)

            # 收盘线价值
            c = m.get('closing', {}).get(closing_book)
            if c:
                cq = implied_probabilities(c)[idx]
                res.clv += (q - cq)   # 下注时的隐含概率 vs 收盘隐含概率

            equity += (frac * o if won else 0.0) - frac
            peak = max(peak, equity)
            res.max_drawdown = max(res.max_drawdown, peak - equity)

        elo.update(m['home'], m['away'], m['ftr'])

    if res.stake > 0:
        res.roi = (res.returns - res.stake) / res.stake * 100
    if res.bets:
        res.hit_rate = res.wins / res.bets * 100
        res.clv /= res.bets
    return res


# ============================================================
# 4. 随机下注基线
# ============================================================
def backtest_random(matches: Sequence[Dict], book: str = 'Pinnacle',
                     n_trials: int = 2000, seed: int = 42) -> Dict:
    """随机选 1 个结果下注的 ROI 基线 (直接反映抽水)"""
    rng = np.random.default_rng(seed)
    items = [(m['odds'][book], m['ftr'])
             for m in matches if book in m.get('odds', {})]
    if not items:
        return {}
    profits = []
    for _ in range(n_trials):
        i = rng.integers(0, len(items))
        odds, ftr = items[i]
        j = rng.integers(0, 3)
        won = (ftr == 'HDA'[j])
        profits.append(odds[j] - 1 if won else -1)
    arr = np.array(profits)
    return {
        'roi': float(arr.mean() * 100),
        'std': float(arr.std() * 100),
        'trials': n_trials,
        'n_matches': len(items),
    }


# ============================================================
# 5. 汇总
# ============================================================
def run_full_analysis(matches: Sequence[Dict],
                       books: Optional[Sequence[str]] = None,
                       value_books: Sequence[str] = ('Pinnacle', 'B365', 'Avg')) -> Dict:
    """完整竞彩期望值分析"""
    if not matches:
        raise ValueError('无比赛数据')

    all_books = set()
    for m in matches:
        all_books.update(m.get('odds', {}).keys())
    if books is None:
        books = sorted(all_books)

    vig_stats = analyze_vig(matches)

    # 套利: 只用独立公司 (排除聚合列)
    real_books = [b for b in books if b not in ('Max', 'Avg')]
    arb = analyze_arb(matches, real_books) if len(real_books) >= 3 else {
        'count': 0, 'checked': 0, 'rate': 0, 'max_profit': 0,
        'mean_profit': 0, 'best': None, 'arbs': []}
    arb_backtest = (backtest_arbs(matches, real_books)
                    if len(real_books) >= 3 else {})

    # 价值下注回测
    value_results = {}
    for b in value_books:
        if b in all_books:
            value_results[b] = backtest_value_bets(matches, book=b)

    # 随机基线
    randoms = {}
    for b in value_books:
        if b in all_books:
            randoms[b] = backtest_random(matches, book=b)

    return {
        'n_matches': len(matches),
        'books': books,
        'vig': vig_stats,
        'arb': arb,
        'arb_backtest': arb_backtest,
        'value_bets': value_results,
        'random_baseline': randoms,
        'conclusion': _conclusion(vig_stats, arb, value_results, randoms,
                                   arb_backtest),
    }


def _conclusion(vig_stats, arb, value_results, randoms, arb_bt=None) -> str:
    parts = []
    if vig_stats:
        ranked = sorted(vig_stats.items(), key=lambda x: x[1]['mean'])
        parts.append(f'抽水最低 {ranked[0][0]} {ranked[0][1]["mean"]*100:.2f}%, '
                     f'最高 {ranked[-1][0]} {ranked[-1][1]["mean"]*100:.2f}%')
    if arb.get('count'):
        s = f'跨公司套利 {arb["count"]}/{arb["checked"]} 场 ({arb["rate"]:.1f}%)'
        if arb_bt and arb_bt.get('count'):
            s += (f', 资金回测 ROI {arb_bt["roi"]:+.2f}% '
                  f'(投 {arb_bt["stake"]:,.0f} 赚 {arb_bt["net"]:,.0f})')
        parts.append(s)
    else:
        parts.append('跨公司套利: 无 (Σ(1/odds) 始终 ≥ 1)')
    if value_results:
        best = max(value_results.items(), key=lambda x: x[1].roi)
        parts.append(f'Elo 价值下注最好 {best[0]} ROI {best[1].roi:+.2f}%')
    if randoms:
        rb = next(iter(randoms.values()))
        parts.append(f'随机下注 ROI {rb["roi"]:+.2f}%')
    return ' | '.join(parts)


__all__ = [
    'implied_probabilities', 'devig', 'vig', 'analyze_vig',
    'ArbOpportunity', 'find_arbs', 'analyze_arb',
    'EloModel', 'ValueBetResult', 'backtest_value_bets', 'backtest_random',
    'run_full_analysis',
]
