"""
胆拖结构优化器
==============
给定**预算**和**优化目标**, 自动搜索最优的胆拖结构并给出具体号码。

★ 依赖 v2.5.0 证明的定理:
  固定号码池下, 中奖率只取决于**胆码个数 + 拖码池大小**,
  与"胆码具体选哪几个号"完全无关。
  → 所以优化分两步:
     1) 搜**结构** (k, t_f, m, t_b) —— 决定所有概率指标
     2) **填号码** —— 只影响"看起来顺眼", 不影响概率 (这一点会在输出里明说)

★ 这也意味着: "追热号"在优化器里没有任何加成, 因为它不改变任何概率。

搜索空间 (以大乐透为例):
  k   前区胆码个数   0..5
  t_f 前区拖码池大小  (5-k)..P_f
  m   后区胆码个数   0..2
  t_b 后区拖码池大小  (2-m)..P_b
  注数 = C(t_f, 5-k) × C(t_b, 2-m),  花费 = 注数 × 单价

用法:
  from data.dan_tuo_optimizer import optimize
  r = optimize('dlt', budget=1680, goal='win')
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb
from typing import Dict, List, Optional

from data.dan_tuo_exact import exact_dan_tuo
from data.games import get_game, get_prize_rules

# ============================================================
# 目标定义
# ============================================================
GOALS = {
    # 目标名 -> (中文名, 说明)
    'win': ('最大中奖率', '任意奖级都算中'),
    'big': ('最大中大奖概率', '命中 ≥ 指定金额的奖级 (默认 3000 元 = 四等奖及以上)'),
    'value': ('最大性价比', '每元钱换到的中奖率'),
    'jackpot': ('最大一等奖概率', '只看向头奖'),
    'covernum': ('最大注数覆盖', '同样的钱买最多的注'),
}

# 目标名 -> 该目标下"大额奖级"的判定门槛 (元)
GOAL_THRESHOLD = {
    'big': 3000,
    'jackpot': 5_000_000,
}


@dataclass
class Candidate:
    """一个候选结构"""
    game: str
    k: int              # 前区胆码个数
    t_f: int            # 前区拖码池大小
    m: int              # 后区胆码个数
    t_b: int            # 后区拖码池大小
    n_bets: int
    cost: float
    win_rate: float     # %
    prize_prob: Dict[str, float] = field(default_factory=dict)
    expected_return: float = 0.0
    expected_net: float = 0.0
    roi: float = 0.0

    @property
    def structure(self) -> str:
        return f'前 {self.k} 胆/{self.t_f} 拖 × 后 {self.m} 胆/{self.t_b} 拖'

    def prob_at_least(self, threshold: float) -> float:
        """命中金额 ≥ threshold 的概率 (%)"""
        return sum(p for lab, p in self.prize_prob.items()
                   if self._money_of(lab) >= threshold)

    def _money_of(self, label: str) -> float:
        for cond, info in get_prize_rules(self.game):
            if info[0] == label:
                return float(info[1]) if len(info) > 1 else 0.0
        return 0.0


def _score(c: Candidate, goal: str, threshold: float) -> float:
    """目标函数值 (越大越好)"""
    if goal == 'win':
        return c.win_rate
    if goal == 'big':
        return c.prob_at_least(threshold)
    if goal == 'jackpot':
        return c.prob_at_least(5_000_000)
    if goal == 'value':
        return c.win_rate / c.cost if c.cost else 0.0
    if goal == 'covernum':
        return float(c.n_bets)
    return c.win_rate


def _enumerate_structures(game: str, budget: float,
                          p_f: int, p_b: int, min_bets: int = 0) -> List[Candidate]:
    """枚举所有满足预算的结构, 用精确求解器算概率"""
    cfg = get_game(game)
    price = cfg.ticket_price
    out = []
    # 占位号码 (号码不影响概率, 只影响结构计算)
    for k in range(0, cfg.front_count + 1):
        need_f = cfg.front_count - k
        # ★ 拖码池最大只能是 p_f - k (拖码与胆码都在同一个池子里, 不能重叠)
        for t_f in range(need_f, p_f - k + 1):
            n_f_combos = comb(t_f, need_f)
            for m in range(0, cfg.back_count + 1):
                need_b = cfg.back_count - m
                for t_b in range(need_b, p_b - m + 1):
                    n_b_combos = comb(t_b, need_b)
                    n_bets = n_f_combos * n_b_combos
                    cost = n_bets * price
                    if cost > budget:
                        continue
                    if n_bets < min_bets:
                        continue
                    fd = list(range(1, k + 1))
                    ft = list(range(k + 1, k + 1 + t_f))
                    bd = list(range(1, m + 1))
                    bt = list(range(m + 1, m + 1 + t_b))
                    r = exact_dan_tuo(game, fd, ft, bd, bt)
                    pp = {p['label']: p['prob_any'] * 100
                          for p in r['prize_dist'] if p['money'] > 0}
                    out.append(Candidate(
                        game=game, k=k, t_f=t_f, m=m, t_b=t_b,
                        n_bets=n_bets, cost=cost,
                        win_rate=r['win_rate'], prize_prob=pp,
                        expected_return=r['expected_return'],
                        expected_net=r['expected_net'], roi=r['roi'],
                    ))
    return out


def _fill_numbers(game: str, cand: Candidate,
                   front_pool: Optional[List[int]],
                   back_pool: Optional[List[int]],
                   fill: str = 'hot') -> tuple:
    """
    给结构填具体号码。

    ★ 重要: 号码选择**不影响任何概率** (v2.5.0 定理)。
      这里只是让方案"看起来顺眼" —— fill='hot' 按冷热排名填,
      'cold' 按冷→热填, 'random' 随机填, 'asis' 按传入顺序。
    """
    cfg = get_game(game)
    if front_pool is None:
        front_pool = list(range(1, cfg.front_range + 1))
    if back_pool is None:
        back_pool = list(range(1, cfg.back_range + 1))

    def take(pool, n, mode):
        pool = sorted(pool)
        if mode == 'hot':
            return pool[:n]
        if mode == 'cold':
            return pool[-n:] if n else []
        if mode == 'random':
            import random
            return sorted(random.sample(pool, n)) if n <= len(pool) else pool
        return pool[:n]

    fd = take(front_pool, cand.k, fill)
    ft = [x for x in take(front_pool, cand.t_f + cand.k, fill) if x not in set(fd)]
    bd = take(back_pool, cand.m, fill)
    bt = [x for x in take(back_pool, cand.t_b + cand.m, fill) if x not in set(bd)]
    return sorted(fd), sorted(ft), sorted(bd), sorted(bt)


def optimize(game: str = 'dlt',
             budget: float = 100.0,
             goal: str = 'win',
             big_threshold: Optional[float] = None,
             front_pool: Optional[List[int]] = None,
             back_pool: Optional[List[int]] = None,
             pool_size_f: Optional[int] = None,
             pool_size_b: Optional[int] = None,
             fill: str = 'hot',
             top_n: int = 8,
             max_cost: Optional[float] = None,
             min_bets: int = 0) -> dict:
    """
    优化胆拖结构。

    Args:
      game          'dlt' / 'ssq'
      budget        预算上限 (元)
      goal          'win' / 'big' / 'value' / 'jackpot' / 'covernum'
      big_threshold 'big' 目标下的大奖门槛 (元), 默认 3000
      front_pool    前区候选号码池 (None = 用全池)
      back_pool     后区候选号码池
      pool_size_f   若不给号码池, 搜索这个大小的池 (None = 遍历所有大小)
      pool_size_b
      fill          填号码策略 'hot'/'cold'/'random'/'asis'
      top_n         返回前 N 个候选
      max_cost      实际允许的最大花费 (默认 = budget)
      min_bets      最少注数 (用于避免 'value' 目标退化成 1 注)

    Returns:
      {goal, goal_cn, budget, best, candidates, searched}
    """
    cfg = get_game(game)
    if goal not in GOALS:
        raise ValueError(f'未知目标 {goal}, 可选: {list(GOALS)}')
    threshold = big_threshold if big_threshold is not None \
        else GOAL_THRESHOLD.get(goal, 3000)
    cost_cap = max_cost if max_cost is not None else budget

    # ★ 'value' (每元钱换到的中奖率) 会退化成"买最便宜的 1 注"——
    #   数学上没错, 但没有实际意义。默认给一个注数下限。
    if min_bets <= 0 and goal == 'value':
        min_bets = 20

    p_f = pool_size_f if pool_size_f is not None else (
        len(front_pool) if front_pool else cfg.front_range)
    p_b = pool_size_b if pool_size_b is not None else (
        len(back_pool) if back_pool else cfg.back_range)

    cands = _enumerate_structures(game, cost_cap, p_f, p_b, min_bets)
    if not cands:
        return {'goal': goal, 'goal_cn': GOALS[goal][0], 'budget': budget,
                'best': None, 'candidates': [], 'searched': 0,
                'note': '预算太小, 没有任何结构买得起 (最少 1 注)'}

    # 目标函数排序; 同分时偏好"更贴近预算" (钱花得值) + 注数多
    cands.sort(key=lambda c: (
        -_score(c, goal, threshold),
        -abs(c.cost - budget),
        -c.n_bets,
    ))

    results = []
    for c in cands[:top_n]:
        fd, ft, bd, bt = _fill_numbers(game, c, front_pool, back_pool, fill)
        results.append({
            'structure': c.structure,
            'k': c.k, 't_f': c.t_f, 'm': c.m, 't_b': c.t_b,
            'n_bets': c.n_bets, 'cost': c.cost,
            'win_rate': c.win_rate,
            'big_prob': c.prob_at_least(threshold),
            'expected_return': c.expected_return,
            'expected_net': c.expected_net,
            'roi': c.roi,
            'prize_prob': c.prize_prob,
            'front_dan': fd, 'front_tuo': ft,
            'back_dan': bd, 'back_tuo': bt,
        })

    best = results[0]
    # 奖级 → 金额, 供前端显示
    prize_money = {}
    for cond, info in get_prize_rules(game):
        prize_money[info[0]] = float(info[1]) if len(info) > 1 else 0.0
    return {
        'goal': goal,
        'goal_cn': GOALS[goal][0],
        'goal_desc': GOALS[goal][1],
        'threshold': threshold,
        'budget': budget,
        'cost_cap': cost_cap,
        'best': best,
        'candidates': results,
        'searched': len(cands),
        'prize_money': prize_money,
        'note': ('号码选择不影响任何概率 —— 概率只由结构决定 '
                 '(v2.5.0 定理: 固定号码池下中奖率只取决于胆码个数与拖码池大小)'),
    }
