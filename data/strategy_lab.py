"""
预测玩法实验室 (Strategy Lab)
===============================
用严格 walk-forward 回测检验各种选号策略是否有效。

方法论 (绝不用未来数据):
  for t in range(start, len(data)):
      train = data[max(0, t-window) : t]      # 只看 t 之前
      pick  = strategy.pick(train)            # 基于过去选号
      reward = judge(pick, data[t])           # 用 t 期真实开奖评判
  每期都重新训练, 严格因果

对照基线:
  随机策略跑 N 个种子取均值, 因为单次随机结果方差极大,
  直接比单条随机曲线没有意义。

核心问题: 任何策略的 ROI 是否能显著超过派奖率 (~50%)?
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from data.games import get_game
from data.pick_advisor import Pick, judge_prize


# ============================================================
# 策略基类
# ============================================================
class BaseStrategy:
    """选号策略基类"""

    name = 'base'
    desc = ''
    uses_back_hot = True     # 后区是否用热号 (多数策略共用)

    def pick(self, ctx: 'Context') -> Tuple[List[int], List[int]]:
        """基于 ctx 提供的历史选号, 返回 (前区, 后区)"""
        raise NotImplementedError


@dataclass
class Context:
    """策略可见的历史窗口 (严格只含预测时点之前的数据)"""
    game: str
    front: np.ndarray        # (n, front_count)  int
    back: np.ndarray         # (n, back_count)   int
    front_range: int
    back_range: int
    front_count: int
    back_count: int

    @property
    def n(self) -> int:
        return len(self.front)

    def front_freq(self) -> np.ndarray:
        """前区每个号的历史出现次数"""
        cnt = np.zeros(self.front_range + 1, dtype=np.int64)
        for v in self.front.ravel():
            if 1 <= v <= self.front_range:
                cnt[v] += 1
        return cnt

    def back_freq(self) -> np.ndarray:
        cnt = np.zeros(self.back_range + 1, dtype=np.int64)
        for v in self.back.ravel():
            if 1 <= v <= self.back_range:
                cnt[v] += 1
        return cnt

    def front_missing(self) -> np.ndarray:
        """前区每个号距上次出现的期数 (从未出现 = n)"""
        last = np.full(self.front_range + 1, self.n, dtype=np.int64)
        for i in range(self.n - 1, -1, -1):
            for v in self.front[i]:
                if 1 <= v <= self.front_range and last[v] == self.n:
                    last[v] = self.n - 1 - i
        return last

    def back_missing(self) -> np.ndarray:
        last = np.full(self.back_range + 1, self.n, dtype=np.int64)
        for i in range(self.n - 1, -1, -1):
            for v in self.back[i]:
                if 1 <= v <= self.back_range and last[v] == self.n:
                    last[v] = self.n - 1 - i
        return last

    def front_recent(self, k: int) -> np.ndarray:
        """最近 k 期的前区号码频次"""
        sub = self.front[-k:]
        cnt = np.zeros(self.front_range + 1, dtype=np.int64)
        for v in sub.ravel():
            if 1 <= v <= self.front_range:
                cnt[v] += 1
        return cnt


# ============================================================
# 具体策略
# ============================================================
def _pick_by_score(ctx: Context, score: np.ndarray, back_score: np.ndarray,
                   avoid_dup: bool = True) -> Tuple[List[int], List[int]]:
    """按分数从高到低取号 (分数可为负, 越大越优先)"""
    front = []
    order = np.argsort(-score[1:]) + 1
    for v in order:
        if 1 <= v <= ctx.front_range and v not in front:
            front.append(int(v))
            if len(front) == ctx.front_count:
                break
    back = []
    border = np.argsort(-back_score[1:]) + 1
    for v in border:
        if 1 <= v <= ctx.back_range and v not in back:
            back.append(int(v))
            if len(back) == ctx.back_count:
                break
    return sorted(front), sorted(back)


class RandomStrategy(BaseStrategy):
    name = 'random'
    desc = '随机选号 (基线对照)'

    def __init__(self, seed: int = 0):
        self.seed = seed

    def pick(self, ctx: Context):
        rng = np.random.default_rng(self.seed + ctx.n)
        f = sorted(rng.choice(np.arange(1, ctx.front_range + 1),
                              ctx.front_count, replace=False).tolist())
        b = sorted(rng.choice(np.arange(1, ctx.back_range + 1),
                              ctx.back_count, replace=False).tolist())
        return f, b


class HotStrategy(BaseStrategy):
    name = 'hot'
    desc = '热号追踪 (历史出现最多的号)'

    def pick(self, ctx: Context):
        return _pick_by_score(ctx, ctx.front_freq(), ctx.back_freq())


class ColdStrategy(BaseStrategy):
    name = 'cold'
    desc = '冷号追踪 (历史出现最少的号)'

    def pick(self, ctx: Context):
        return _pick_by_score(ctx, -ctx.front_freq(), -ctx.back_freq())


class MaxMissingStrategy(BaseStrategy):
    name = 'max_missing'
    desc = '遗漏最久 (该出了谬论)'

    def pick(self, ctx: Context):
        return _pick_by_score(ctx, ctx.front_missing(), ctx.back_missing())


class HotRecentStrategy(BaseStrategy):
    name = 'hot_recent'
    desc = '近 30 期加权热号 (只看最近)'

    def pick(self, ctx: Context):
        k = min(30, ctx.n)
        return _pick_by_score(ctx, ctx.front_recent(k), ctx.back_freq())


class BayesianStrategy(BaseStrategy):
    name = 'bayesian'
    desc = '贝叶斯后验 (先验 + 似然平滑)'

    def pick(self, ctx: Context):
        # 用最近 200 期做似然, 前 300 期做先验 (避免早期数据过度影响)
        k = min(200, ctx.n)
        sub = ctx.front[-k:]
        cnt = np.zeros(ctx.front_range + 1, dtype=np.float64)
        for v in sub.ravel():
            if 1 <= v <= ctx.front_range:
                cnt[v] += 1
        prior = ctx.front_freq().astype(np.float64)
        prior = prior / max(1.0, prior.sum())
        # 后验 ∝ 先验 + 似然
        post = prior + cnt / max(1.0, cnt.sum())
        bpost = ctx.back_freq().astype(np.float64)
        bpost = bpost / max(1.0, bpost.sum()) + ctx.back_freq() / max(1.0, ctx.back_freq().sum())
        return _pick_by_score(ctx, post, bpost)


class MarkovStrategy(BaseStrategy):
    name = 'markov'
    desc = '一阶马尔可夫 (上期开的号后面最常跟谁)'

    def pick(self, ctx: Context):
        if ctx.n < 2:
            return _pick_by_score(ctx, ctx.front_freq(), ctx.back_freq())
        # 统计"某号出现后, 下一期各号出现次数"
        trans = np.zeros((ctx.front_range + 1, ctx.front_range + 1),
                         dtype=np.float64)
        for i in range(ctx.n - 1):
            for a in ctx.front[i]:
                for b in ctx.front[i + 1]:
                    if 1 <= a <= ctx.front_range and 1 <= b <= ctx.front_range:
                        trans[a, b] += 1
        last = ctx.front[-1]
        score = trans[last].copy()
        # 没有转移信息时回退到频次
        if score.sum() == 0:
            score = ctx.front_freq().astype(np.float64)
        else:
            score = score / score.sum() + ctx.front_freq() / max(
                1.0, ctx.front_freq().sum())
        return _pick_by_score(ctx, score, ctx.back_freq())


class ZoneBalanceStrategy(BaseStrategy):
    name = 'zone_balance'
    desc = '区间均衡 (每个号段至少 1 个)'

    def pick(self, ctx: Context):
        freq = ctx.front_freq()
        rng = ctx.front_range
        zones = [(1, 11), (12, 23), (24, rng)]
        front = []
        for lo, hi in zones:
            best = max(range(lo, hi + 1), key=lambda v: (freq[v], -v))
            front.append(best)
        # 剩余名额按频次补
        need = ctx.front_count - len(front)
        order = np.argsort(-freq[1:]) + 1
        for v in order:
            if need <= 0:
                break
            if 1 <= v <= rng and int(v) not in front:
                front.append(int(v))
                need -= 1
        back = _pick_by_score(ctx, freq, ctx.back_freq())[1]
        return sorted(front), back


class OddEvenStrategy(BaseStrategy):
    name = 'odd_even'
    desc = '奇偶比 3:2'

    def pick(self, ctx: Context):
        rng = ctx.front_range
        odds = [v for v in range(1, rng + 1) if v % 2 == 1]
        evens = [v for v in range(1, rng + 1) if v % 2 == 0]
        freq = ctx.front_freq()
        n_odd = min(len(odds), 3)
        n_even = ctx.front_count - n_odd
        front = sorted([v for v in odds if v % 2 == 1][:0]
                       + sorted(sorted(odds, key=lambda v: -freq[v])[:n_odd])
                       + sorted(sorted(evens, key=lambda v: -freq[v])[:n_even]))
        back = _pick_by_score(ctx, freq, ctx.back_freq())[1]
        return front, back


class PrimeCompositeStrategy(BaseStrategy):
    name = 'prime_composite'
    desc = '质合比 3:2 (质数优先)'

    def pick(self, ctx: Context):
        rng = ctx.front_range

        def is_prime(n):
            if n < 2:
                return False
            for i in range(2, int(math.isqrt(n)) + 1):
                if n % i == 0:
                    return False
            return True

        primes = [v for v in range(1, rng + 1) if is_prime(v)]
        comps = [v for v in range(1, rng + 1) if not is_prime(v)]
        freq = ctx.front_freq()
        n_p = min(len(primes), 3)
        front = sorted(sorted(primes, key=lambda v: -freq[v])[:n_p]
                       + sorted(comps, key=lambda v: -freq[v])[:ctx.front_count - n_p])
        back = _pick_by_score(ctx, freq, ctx.back_freq())[1]
        return front, back


class SumTargetStrategy(BaseStrategy):
    name = 'sum_target'
    desc = '和值瞄准 (复刻历史最常见和值)'

    def pick(self, ctx: Context):
        sums = ctx.front.sum(axis=1)
        vals, cnts = np.unique(sums, return_counts=True)
        target = int(vals[np.argmax(cnts)])
        freq = ctx.front_freq()
        rng = ctx.front_range
        # 贪心凑和值
        front = []
        for _ in range(ctx.front_count):
            best, best_d = None, None
            for v in range(1, rng + 1):
                if v in front:
                    continue
                cur = sum(front) + v
                d = abs(cur - target)
                if len(front) < ctx.front_count - 1:
                    d += 0  # 还有名额, 不那么在意
                if best_d is None or d < best_d or (d == best_d and freq[v] > freq[best]):
                    best, best_d = v, d
            if best:
                front.append(best)
        back = _pick_by_score(ctx, freq, ctx.back_freq())[1]
        return sorted(front), back


class ACValueStrategy(BaseStrategy):
    name = 'ac_value'
    desc = 'AC值最大化 (离散度最优)'

    def pick(self, ctx: Context):
        rng = ctx.front_range
        # 贪心: 每次选与已选集合差异最大的号
        front = []
        while len(front) < ctx.front_count:
            best, best_score = None, -1
            for v in range(1, rng + 1):
                if v in front:
                    continue
                cand = front + [v]
                if len(cand) < 3:
                    score = len(cand)
                else:
                    diffs = {abs(a - b) for a in cand for b in cand if a != b}
                    score = len(diffs)
                if score > best_score:
                    best, best_score = v, score
            if best is None:
                break
            front.append(best)
        back = _pick_by_score(ctx, ctx.front_freq(), ctx.back_freq())[1]
        return sorted(front), back


class RepeatLastStrategy(BaseStrategy):
    name = 'repeat_last'
    desc = '照抄上期号码 (连号/重号谬论)'

    def pick(self, ctx: Context):
        if ctx.n == 0:
            return _pick_by_score(ctx, ctx.front_freq(), ctx.back_freq())
        return sorted(int(v) for v in ctx.front[-1]), sorted(
            int(v) for v in ctx.back[-1])


# ============================================================
# 策略注册表
# ============================================================
def build_strategies() -> Dict[str, BaseStrategy]:
    return {
        s.name: s for s in [
            RandomStrategy(seed=0),
            HotStrategy(),
            ColdStrategy(),
            MaxMissingStrategy(),
            HotRecentStrategy(),
            BayesianStrategy(),
            MarkovStrategy(),
            ZoneBalanceStrategy(),
            OddEvenStrategy(),
            PrimeCompositeStrategy(),
            SumTargetStrategy(),
            ACValueStrategy(),
            RepeatLastStrategy(),
        ]
    }


STRATEGY_DESCRIPTIONS = {
    s.name: s.desc for s in build_strategies().values()
}


# ============================================================
# 回测引擎
# ============================================================
@dataclass
class StrategyResult:
    name: str
    desc: str
    bets: int = 0
    wins: int = 0
    stake: float = 0.0
    returns: float = 0.0
    big_prizes: int = 0          # 三等奖以上 (≥1万) 的次数
    returns_ex_big: float = 0.0  # 剔除大奖后的返奖
    prize_counts: Dict[str, int] = field(default_factory=dict)
    equity_curve: List[float] = field(default_factory=list)

    @property
    def net(self) -> float:
        return self.returns - self.stake

    @property
    def roi(self) -> float:
        return (self.returns - self.stake) / self.stake * 100 if self.stake else 0.0

    @property
    def roi_ex_big(self) -> float:
        """剔除大奖后的常态 ROI (这才是策略之间的真实差异)"""
        if not self.stake:
            return 0.0
        return (self.returns_ex_big - self.stake) / self.stake * 100

    @property
    def win_rate(self) -> float:
        return self.wins / self.bets * 100 if self.bets else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        mdd = 0.0
        for v in self.equity_curve:
            peak = max(peak, v)
            mdd = max(mdd, peak - v)
        return mdd

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'desc': self.desc,
            'bets': self.bets,
            'wins': self.wins,
            'win_rate': round(self.win_rate, 2),
            'stake': round(self.stake, 0),
            'returns': round(self.returns, 0),
            'net': round(self.net, 0),
            'roi': round(self.roi, 2),
            'roi_ex_big': round(self.roi_ex_big, 2),
            'big_prizes': self.big_prizes,
            'returns_ex_big': round(self.returns_ex_big, 0),
            'max_drawdown': round(self.max_drawdown, 0),
            'prizes': sorted(self.prize_counts.items(), key=lambda x: -x[1]),
        }


# 大奖奖级 (剔除后算"常态 ROI")
# ⚠ 不能用固定金额阈值! SSQ 三等奖只有 3000 元, DLT 三等奖 1 万,
#   固定 1 万阈值会让 SSQ 的三等奖混进"常态", 一次就能把 ROI 拉成正的.
#   必须按奖级名判定: 一等奖 / 二等奖 / 三等奖 都算大奖.
BIG_PRIZE_LABELS = ('一等奖', '二等奖', '三等奖')
BIG_PRIZE = 10_000  # 保留兼容 (仅用于显示)


def backtest_strategy(strategy: BaseStrategy, front: np.ndarray,
                      back: np.ndarray, game: str, window: int = 200,
                      start: int = 300) -> StrategyResult:
    """
    严格 walk-forward 回测。

    front/back: (n, k) 完整历史数组
    window: 训练窗口大小 (只看最近 window 期)
    start: 从第几期开始预测 (前面留够训练数据)
    """
    cfg = get_game(game)
    res = StrategyResult(name=strategy.name, desc=strategy.desc)
    n = len(front)

    for t in range(start, n):
        lo = max(0, t - window)
        ctx = Context(
            game=game,
            front=front[lo:t],
            back=back[lo:t],
            front_range=cfg.front_range,
            back_range=cfg.back_range,
            front_count=cfg.front_count,
            back_count=cfg.back_count,
        )
        try:
            f, b = strategy.pick(ctx)
        except Exception:
            continue
        if len(f) != cfg.front_count or len(b) != cfg.back_count:
            continue
        if len(set(f)) != len(f) or len(set(b)) != len(b):
            continue

        label, money = judge_prize(game, Pick(front=f, back=b),
                                   [int(x) for x in front[t]],
                                   [int(x) for x in back[t]])
        res.bets += 1
        res.stake += cfg.ticket_price
        res.returns += money
        if money > 0:
            res.wins += 1
            res.prize_counts[label] = res.prize_counts.get(label, 0) + 1
            # 大奖按奖级名判定 (SSQ 三等奖 3000 元 < DLT 阈值 1 万)
            if label in BIG_PRIZE_LABELS:
                res.big_prizes += 1
            else:
                res.returns_ex_big += money
        res.equity_curve.append(res.returns - res.stake)

    return res


def backtest_random_baseline(front: np.ndarray, back: np.ndarray, game: str,
                              window: int = 200, start: int = 300,
                              n_seeds: int = 20, seed: int = 42) -> Dict:
    """
    随机基线: 跑 n_seeds 个不同种子取分布 (均值 + 标准差 + 最好/最差)
    单次随机结果方差极大, 必须看分布而不是单条曲线
    """
    cfg = get_game(game)
    n = len(front)
    rois = []
    rois_ex_big = []
    nets = []
    win_rates = []
    big_counts = []

    for s in range(n_seeds):
        strat = RandomStrategy(seed=seed + s * 1000)
        r = backtest_strategy(strat, front, back, game, window, start)
        if r.bets:
            rois.append(r.roi)
            rois_ex_big.append(r.roi_ex_big)
            nets.append(r.net)
            win_rates.append(r.win_rate)
            big_counts.append(r.big_prizes)

    if not rois:
        return {'count': 0}

    return {
        'count': len(rois),
        'roi_mean': float(np.mean(rois)),
        'roi_std': float(np.std(rois)),
        'roi_min': float(np.min(rois)),
        'roi_max': float(np.max(rois)),
        'roi_ex_big_mean': float(np.mean(rois_ex_big)),
        'roi_ex_big_std': float(np.std(rois_ex_big)),
        'roi_ex_big_min': float(np.min(rois_ex_big)),
        'roi_ex_big_max': float(np.max(rois_ex_big)),
        'big_mean': float(np.mean(big_counts)),
        'net_mean': float(np.mean(nets)),
        'net_min': float(np.min(nets)),
        'net_max': float(np.max(nets)),
        'win_rate_mean': float(np.mean(win_rates)),
        'win_rate_std': float(np.std(win_rates)),
        'best_roi': float(np.max(rois)),
        'worst_roi': float(np.min(rois)),
    }


def compute_payout_breakdown(game: str) -> Dict:
    """
    把派奖率拆成 大奖部分 / 小奖部分.

    这是理解"为什么所有策略 ROI 都是 -70% 左右"的关键:
      - 理论总 ROI = -49.5% (含大奖)
      - 但大奖期望要买 214 万注才回本, 实际几乎碰不到
      - 小奖部分的期望 ROI ≈ -71.7% ← 所有策略实际都落在这里
    """
    from math import comb
    from data.games import get_prize_rules

    cfg = get_game(game)
    fr, fc = cfg.front_range, cfg.front_count
    br, bc = cfg.back_range, cfg.back_count

    big_exp = 0.0   # 大奖期望奖金/注
    small_exp = 0.0  # 小奖期望奖金/注
    detail = []
    for cond, info in get_prize_rules(game):
        k, j = cond[0], cond[1]
        money = info[1] if isinstance(info, (tuple, list)) and len(info) > 1 else 0
        pf = comb(fc, k) * comb(fr - fc, fc - k) / comb(fr, fc)
        pb = comb(bc, j) * comb(br - bc, bc - j) / comb(br, bc)
        contrib = pf * pb * money
        is_big = money >= BIG_PRIZE
        if is_big:
            big_exp += contrib
        else:
            small_exp += contrib
        detail.append({
            'label': info[0], 'money': money,
            'prob': pf * pb, 'contrib': contrib, 'big': is_big,
        })

    total = big_exp + small_exp
    price = cfg.ticket_price
    return {
        'total_exp': total,
        'total_payout': total / price * 100,
        'big_exp': big_exp,
        'small_exp': small_exp,
        'big_payout': big_exp / price * 100,
        'small_payout': small_exp / price * 100,
        'roi_all': (total - price) / price * 100,
        'roi_small_only': (small_exp - price) / price * 100,
        'big_odds': 1 / (comb(fr, fc) * comb(br, bc)),
        'detail': detail,
    }


def breakeven_win_rate(game: str) -> Dict:
    """
    盈亏平衡中奖率: 中奖率必须高到多少才不亏?

    若所有中奖都是最低奖级 (DLT 九等奖 5 元), 中奖率需 > 2/5 = 40%
    若按八等奖 (15 元), 需 > 2/15 = 13.3%
    现实中奖率约 6-8%, 差了一个数量级.
    """
    from data.games import get_prize_rules
    cfg = get_game(game)
    rules = get_prize_rules(game)
    tiers = []
    for cond, info in rules:
        money = info[1] if isinstance(info, (tuple, list)) and len(info) > 1 else 0
        tiers.append((info[0], money))
    tiers.sort(key=lambda x: x[1])
    lowest = tiers[0]
    return {
        'price': cfg.ticket_price,
        'lowest_prize_label': lowest[0],
        'lowest_prize': lowest[1],
        'breakeven_at_lowest': (cfg.ticket_price / lowest[1] * 100
                                if lowest[1] else 0),
        'tiers': tiers,
    }


def run_lab(game: str = 'dlt', window: int = 200, start: int = 300,
            n_seeds: int = 20, strategies: Optional[List[str]] = None,
            df=None) -> Dict:
    """
    跑完整实验室: 所有策略 + 随机基线 + 结论
    """
    from data.sqlite_storage import SQLiteStorage

    if df is None:
        df = SQLiteStorage().load_dataframe(game)
    if df is None or df.empty:
        raise RuntimeError('数据库为空, 请先跑 python main.py crawl --game all')

    cfg = get_game(game)
    n = len(df)
    front = np.array([[int(row[f'front_{i+1}']) for i in range(cfg.front_count)]
                      for _, row in df.iterrows()], dtype=np.int32)
    back = np.array([[int(row[f'back_{i+1}']) for i in range(cfg.back_count)]
                     for _, row in df.iterrows()], dtype=np.int32)

    start = min(start, max(30, n // 4))
    registry = build_strategies()
    selected = strategies or list(registry.keys())

    results = []
    for name in selected:
        strat = registry.get(name)
        if strat is None:
            continue
        r = backtest_strategy(strat, front, back, game, window, start)
        if r.bets:
            results.append(r.to_dict())

    baseline = backtest_random_baseline(front, back, game, window, start,
                                         n_seeds=n_seeds)

    # 理论派奖率
    from data.pick_advisor import calc_expected_prize
    dummy = Pick(front=[1] * cfg.front_count, back=[1] * cfg.back_count)
    exp1, net1, kelly1, prob1 = calc_expected_prize(game, dummy)
    payout = exp1 / cfg.ticket_price * 100

    # 结论: 有没有策略显著超过随机基线的上界
    best = max(results, key=lambda x: x['roi']) if results else None
    best_ex_big = (max(results, key=lambda x: x['roi_ex_big'])
                   if results else None)
    beat_random = 0
    beat_random_ex_big = 0
    if best and baseline.get('count'):
        for r in results:
            if r['roi'] > baseline['roi_max']:
                beat_random += 1
            if r['roi_ex_big'] > baseline['roi_ex_big_max']:
                beat_random_ex_big += 1

    payout_breakdown = compute_payout_breakdown(game)
    breakeven = breakeven_win_rate(game)

    # 最佳中奖率策略 vs 盈亏平衡所需中奖率
    best_wr = max(results, key=lambda x: x['win_rate']) if results else None
    if best_wr:
        breakeven['best_strategy'] = best_wr['name']
        breakeven['best_win_rate'] = best_wr['win_rate']
        breakeven['gap_factor'] = (breakeven['breakeven_at_lowest']
                                   / best_wr['win_rate']
                                   if best_wr['win_rate'] else 0)

    return {
        'ok': True,
        'game': game,
        'game_name': cfg.name,
        'total_draws': n,
        'tested_draws': n - start,
        'window': window,
        'start': start,
        'ticket_price': cfg.ticket_price,
        'theoretical_payout': round(payout_breakdown['total_payout'], 2),
        'payout_breakdown': payout_breakdown,
        'breakeven': breakeven,
        'expected_net_per_bet': round(net1, 4),
        'kelly': round(kelly1, 3),
        'strategies': results,
        'baseline': baseline,
        'best': best,
        'best_ex_big': best_ex_big,
        'beat_random_count': beat_random,
        'beat_random_ex_big_count': beat_random_ex_big,
        'conclusion': _make_conclusion(results, baseline, payout,
                                       beat_random, beat_random_ex_big),
    }


def _make_conclusion(results, baseline, payout, beat_random,
                     beat_random_ex_big) -> str:
    if not results:
        return '无可用结果'
    best = max(results, key=lambda x: x['roi'])
    worst = min(results, key=lambda x: x['roi'])
    best_x = max(results, key=lambda x: x['roi_ex_big'])
    best_w = max(results, key=lambda x: x['win_rate'])
    lines = []
    lines.append(f'理论派奖率 {payout:.1f}% — 所有策略的 ROI 都应收敛到这里')
    lines.append(f'表面最好: {best["name"]} ROI {best["roi"]:+.1f}% '
                 f'(中了 {best["big_prizes"]} 次大奖)')
    lines.append(f'表面最差: {worst["name"]} ROI {worst["roi"]:+.1f}%')
    lines.append(f'剔除大奖后最好: {best_x["name"]} ROI {best_x["roi_ex_big"]:+.1f}%')
    if baseline.get('count'):
        lines.append(f'随机基线: 均值 {baseline["roi_mean"]:+.1f}% '
                     f'(σ {baseline["roi_std"]:.1f}%), '
                     f'剔除大奖后 {baseline["roi_ex_big_mean"]:+.1f}% '
                     f'(σ {baseline["roi_ex_big_std"]:.1f}%)')
    if beat_random_ex_big == 0:
        lines.append('剔除大奖后, 没有任何策略跑赢随机基线的最好情况')
    else:
        lines.append(f'剔除大奖后有 {beat_random_ex_big} 个策略跑赢随机最好情况 '
                     f'(需检查是否只是采样运气)')
    return ' | '.join(lines)


__all__ = [
    'BaseStrategy', 'Context', 'StrategyResult',
    'build_strategies', 'STRATEGY_DESCRIPTIONS',
    'backtest_strategy', 'backtest_random_baseline', 'run_lab',
]
