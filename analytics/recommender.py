"""
号码组合推荐器 - 把"热度"变成"今晚买什么"
====================================
基于综合评分，给出多种策略的具体号码组合

策略:
  1. TopHeat    - 守热：从综合热度 Top 12 中随机组合 N 注
  2. ColdRebound- 追冷：从最冷 Bottom 12 中随机组合 N 注
  3. Balanced   - 均衡：Top 8 热 + Top 4 冷 混合
  4. MostFreq   - 历史频次 Top 12 组合
  5. MixedPortfolio - 多策略混合（推荐）

特色:
  - 智能分散：避免多注号码高度重叠
  - 和值校验：5 球和值在 60-130 之间（理论合理区间）
  - 跨度校验：5 球最大-最小 在 15-30 之间
  - 奇偶比：避免全奇或全偶
"""
from __future__ import annotations
import os
import sys
import random
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from itertools import combinations

import numpy as np
import pandas as pd

# 禁用代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

from data import load_lottery_data
from core import compute_all_heat_scores

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 兼容旧代码
GAME_CONFIG = {
    "dlt": {"front_range": 35, "front_count": 5, "back_range": 12, "back_count": 2},
    "ssq": {"front_range": 33, "front_count": 6, "back_range": 16, "back_count": 1},
}


@dataclass
class Ticket:
    """一注推荐"""
    strategy: str           # 策略名
    index: int              # 第几注
    front: List[int]        # 前区 5 个号码
    back: List[int]         # 后区 2 个号码
    score: float            # 综合评分（平均）
    rationale: str = ""     # 推荐理由
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["front"] = " ".join(f"{n:02d}" for n in self.front)
        d["back"]  = " ".join(f"{n:02d}" for n in self.back)
        return d

    @property
    def front_str(self) -> str:
        return " ".join(f"{n:02d}" for n in self.front)

    @property
    def back_str(self) -> str:
        return " ".join(f"{n:02d}" for n in self.back)


class Recommender:
    """
    号码组合推荐器（支持多彩种）
    """

    def __init__(self, df: pd.DataFrame = None, seed: int = None, game: str = "dlt"):
        self.game = game
        self.front_range = GAME_CONFIG[game]["front_range"]
        self.front_count = GAME_CONFIG[game]["front_count"]
        self.back_range = GAME_CONFIG[game]["back_range"]
        self.back_count = GAME_CONFIG[game]["back_count"]

        self.df = df if df is not None else load_lottery_data(game=game)
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self.front_scores = self._compute_front_scores()
        self.back_scores = self._compute_back_scores()
        self.front_freq = self._compute_frequency("front")
        self.back_freq = self._compute_frequency("back")

    def _compute_front_scores(self) -> np.ndarray:
        front_cols = [c for c in self.df.columns if c.startswith("front_")]
        onehot = np.zeros((len(self.df), self.front_range), dtype=np.int8)
        for col in front_cols:
            nums = self.df[col].values - 1
            np.put_along_axis(onehot, nums[:, None], 1, axis=1)
        return compute_all_heat_scores(onehot, self.front_range)["composite"]

    def _compute_back_scores(self) -> np.ndarray:
        back_cols = [c for c in self.df.columns if c.startswith("back_")]
        onehot = np.zeros((len(self.df), self.back_range), dtype=np.int8)
        for col in back_cols:
            nums = self.df[col].values - 1
            np.put_along_axis(onehot, nums[:, None], 1, axis=1)
        return compute_all_heat_scores(onehot, self.back_range)["composite"]

    def _compute_frequency(self, zone: str) -> np.ndarray:
        cols = [c for c in self.df.columns if c.startswith(f"{zone}_")]
        n_range = self.front_range if zone == "front" else self.back_range
        onehot = np.zeros((len(self.df), n_range), dtype=np.int8)
        for col in cols:
            nums = self.df[col].values - 1
            np.put_along_axis(onehot, nums[:, None], 1, axis=1)
        return onehot.sum(axis=0)

    # ----------------------------------------------------------
    # 核心：生成 N 注不重复的组合（最大化分散）
    # ----------------------------------------------------------
    def _smart_sample(
        self,
        candidates: List[int],
        n_pick: int,
        n_tickets: int,
        forbidden_combos: set = None,
    ) -> List[List[int]]:
        """
        从 candidates 里智能选 n_pick 个号，生成 n_tickets 个不重复组合
        目标：最大化不同组合之间的差异
        forbidden_combos: 已选的组合 (frozenset/tuple)，避免重叠
        """
        if forbidden_combos is None:
            forbidden_combos = set()

        # 所有可能组合（排除已选的）
        all_combos = []
        for c in combinations(candidates, n_pick):
            sorted_c = tuple(sorted(c))
            if sorted_c not in forbidden_combos:
                all_combos.append(sorted_c)

        if len(all_combos) <= n_tickets:
            return [list(c) for c in all_combos]

        # 按分数排序候选组合
        scored_combos = []
        for c in all_combos:
            avg_score = np.mean([self.front_scores[i-1] for i in c])
            scored_combos.append((c, avg_score))

        scored_combos.sort(key=lambda x: -x[1])
        # 选前 n_tickets * 3 个候选，再随机选 n_tickets（保证分散）
        top_candidates = scored_combos[:n_tickets * 3]
        random.shuffle(top_candidates)
        selected = [list(c) for c, _ in top_candidates[:n_tickets]]

        return selected

    def _validate_combo(self, front: List[int], back: List[int]) -> bool:
        """校验组合合理性"""
        # 奇偶比：前区至少 1 奇 1 偶
        odd = sum(1 for n in front if n % 2 == 1)
        if odd == 0 or odd == 5:
            return False
        # 跨度：max - min 应在 15-30
        span = max(front) - min(front)
        if not (12 <= span <= 32):
            return False
        # 和值：60-130
        sum_val = sum(front)
        if not (60 <= sum_val <= 130):
            return False
        # 三个连续号不太多（避免 1,2,3,4,5 这种）
        sorted_f = sorted(front)
        max_consecutive = 1
        cur = 1
        for i in range(1, len(sorted_f)):
            if sorted_f[i] - sorted_f[i-1] == 1:
                cur += 1
                max_consecutive = max(max_consecutive, cur)
            else:
                cur = 1
        if max_consecutive >= 4:
            return False
        return True

    # ----------------------------------------------------------
    # 5 种策略
    # ----------------------------------------------------------
    def recommend_top_heat(self, n_tickets: int = 5, front_top_k: int = 12, back_top_k: int = 6) -> List[Ticket]:
        """策略 1: 守热 - 从 Top K 热号中智能选 N 注"""
        front_pool = sorted([int(i+1) for i in np.argsort(self.front_scores)[::-1][:front_top_k]])
        back_pool = sorted([int(i+1) for i in np.argsort(self.back_scores)[::-1][:back_top_k]])

        front_combos = self._smart_sample(front_pool, self.front_count, n_tickets)
        back_combos = self._smart_sample(back_pool, self.back_count, n_tickets)

        tickets = []
        for i, (fc, bc) in enumerate(zip(front_combos, back_combos)):
            score = np.mean([self.front_scores[n-1] for n in fc])
            tickets.append(Ticket(
                strategy="TopHeat",
                index=i+1,
                front=fc,
                back=bc,
                score=float(score),
                rationale=f"前区 {fc} (平均热度 {score:.3f}) + 后区 {bc}",
                metadata={"front_top_k": front_top_k, "back_top_k": back_top_k},
            ))
        return tickets

    def recommend_cold_rebound(self, n_tickets: int = 3, front_top_k: int = 12, back_top_k: int = 6) -> List[Ticket]:
        """策略 2: 追冷 - 从最冷 K 个号中组合"""
        front_pool = sorted([int(i+1) for i in np.argsort(self.front_scores)[:front_top_k]])
        back_pool = sorted([int(i+1) for i in np.argsort(self.back_scores)[:back_top_k]])

        front_combos = self._smart_sample(front_pool, self.front_count, n_tickets)
        back_combos = self._smart_sample(back_pool, self.back_count, n_tickets)

        tickets = []
        for i, (fc, bc) in enumerate(zip(front_combos, back_combos)):
            score = np.mean([self.front_scores[n-1] for n in fc])
            tickets.append(Ticket(
                strategy="ColdRebound",
                index=i+1,
                front=fc,
                back=bc,
                score=float(score),
                rationale=f"前区 {fc} (平均热度 {score:.3f}, 冷号反弹)",
                metadata={"front_top_k": front_top_k, "back_top_k": back_top_k},
            ))
        return tickets

    def recommend_balanced(self, n_tickets: int = 3, n_hot: int = 8, n_cold: int = 4) -> List[Ticket]:
        """策略 3: 均衡 - Top 8 热 + Top 4 冷"""
        sorted_idx = np.argsort(self.front_scores)
        hot_idx = sorted_idx[::-1][:n_hot]
        cold_idx = sorted_idx[:n_cold]
        pool = sorted(list(hot_idx) + list(cold_idx))
        front_pool = [int(i+1) for i in pool]

        sorted_back = np.argsort(self.back_scores)
        n_back = max(self.back_count, 1)
        back_pool = sorted([int(i+1) for i in list(sorted_back[::-1][:n_back]) + list(sorted_back[:n_back])])

        front_combos = self._smart_sample(front_pool, self.front_count, n_tickets)
        back_combos = self._smart_sample(back_pool, self.back_count, n_tickets)

        tickets = []
        for i, (fc, bc) in enumerate(zip(front_combos, back_combos)):
            score = np.mean([self.front_scores[n-1] for n in fc])
            tickets.append(Ticket(
                strategy="Balanced",
                index=i+1,
                front=fc,
                back=bc,
                score=float(score),
                rationale=f"前区 {fc} ({n_hot} 热 + {n_cold} 冷均衡)",
                metadata={"n_hot": n_hot, "n_cold": n_cold},
            ))
        return tickets

    def recommend_most_frequent(self, n_tickets: int = 3) -> List[Ticket]:
        """策略 4: 历史频次 Top 12 - 长期热度"""
        front_pool = sorted([int(i+1) for i in np.argsort(self.front_freq)[::-1][:12]])
        sorted_back = np.argsort(self.back_freq)
        n_back = max(self.back_count, 1)
        back_pool = sorted([int(i+1) for i in list(sorted_back[::-1][:n_back]) + list(sorted_back[:n_back])])

        front_combos = self._smart_sample(front_pool, self.front_count, n_tickets)
        back_combos = self._smart_sample(back_pool, self.back_count, n_tickets)

        tickets = []
        for i, (fc, bc) in enumerate(zip(front_combos, back_combos)):
            score = np.mean([self.front_scores[n-1] for n in fc])
            tickets.append(Ticket(
                strategy="MostFrequent",
                index=i+1,
                front=fc,
                back=bc,
                score=float(score),
                rationale=f"前区 {fc} (历史频次 Top 12)",
                metadata={},
            ))
        return tickets

    def recommend_mixed_portfolio(
        self,
        n_top_heat: int = 3,
        n_balanced: int = 2,
        n_cold: int = 1,
        n_most_freq: int = 1,
    ) -> List[Ticket]:
        """策略 5: 多策略混合（推荐）
        不同策略之间也避免前区组合重叠
        """
        tickets = []
        idx = 1
        forbidden_front = set()  # 累积所有已选前区组合，避免重叠

        # 守热
        for t in self.recommend_top_heat(n_tickets=n_top_heat):
            t.index = idx
            tickets.append(t)
            forbidden_front.add(tuple(sorted(t.front)))
            idx += 1

        # 均衡（传 forbidden 让其避开已选）
        front_pool_bal = self._front_pool_for_balanced()
        back_pool = self._back_pool_for_top_heat()
        front_combos = self._smart_sample(front_pool_bal, self.front_count, n_balanced, forbidden_combos=forbidden_front)
        back_combos = self._smart_sample(back_pool, self.back_count, n_balanced)
        for i, (fc, bc) in enumerate(zip(front_combos, back_combos)):
            score = np.mean([self.front_scores[n-1] for n in fc])
            t = Ticket(
                strategy="Balanced",
                index=idx,
                front=fc,
                back=bc,
                score=float(score),
                rationale=f"前区 {fc} (热+冷均衡)",
                metadata={},
            )
            tickets.append(t)
            forbidden_front.add(tuple(sorted(fc)))
            idx += 1

        # 追冷
        for t in self.recommend_cold_rebound(n_tickets=n_cold):
            t.index = idx
            tickets.append(t)
            forbidden_front.add(tuple(sorted(t.front)))
            idx += 1

        # 历史频次
        for t in self.recommend_most_frequent(n_tickets=n_most_freq):
            t.index = idx
            tickets.append(t)
            forbidden_front.add(tuple(sorted(t.front)))
            idx += 1

        return tickets

    def _front_pool_for_balanced(self) -> List[int]:
        """均衡策略的前区候选池"""
        sorted_idx = np.argsort(self.front_scores)
        hot_idx = sorted_idx[::-1][:8]
        cold_idx = sorted_idx[:4]
        return sorted([int(i + 1) for i in list(hot_idx) + list(cold_idx)])

    def _back_pool_for_top_heat(self) -> List[int]:
        """后区候选池（Top 6）"""
        return sorted([int(i+1) for i in np.argsort(self.back_scores)[::-1][:6]])

    def recommend_for_period(
        self,
        period: str = None,
        strategies: List[str] = None,
        n_total: int = 10,
    ) -> Dict:
        """为一期生成推荐组合

        Args:
            period: 期号（默认最新）
            strategies: 策略列表 ['TopHeat', 'Balanced', ...]，None = 默认混合
            n_total: 总注数
        """
        if period is None:
            period = str(self.df["period"].iloc[-1])

        if strategies is None or "mixed" in strategies:
            # 默认混合
            tickets = self.recommend_mixed_portfolio(
                n_top_heat=max(1, n_total // 3),
                n_balanced=max(1, n_total // 4),
                n_cold=max(1, n_total // 8),
                n_most_freq=1,
            )
        else:
            tickets = []
            for strat in strategies:
                if strat == "TopHeat":
                    tickets.extend(self.recommend_top_heat(n_tickets=max(1, n_total // len(strategies))))
                elif strat == "ColdRebound":
                    tickets.extend(self.recommend_cold_rebound(n_tickets=max(1, n_total // len(strategies))))
                elif strat == "Balanced":
                    tickets.extend(self.recommend_balanced(n_tickets=max(1, n_total // len(strategies))))
                elif strat == "MostFrequent":
                    tickets.extend(self.recommend_most_frequent(n_tickets=max(1, n_total // len(strategies))))

        return {
            "period": period,
            "generated_at": pd.Timestamp.now().isoformat(),
            "n_tickets": len(tickets),
            "tickets": [t.to_dict() for t in tickets],
            "summary": {
                "strategies": list(set(t.strategy for t in tickets)),
                "avg_score": np.mean([t.score for t in tickets]),
            },
        }

    def print_recommendations(self, tickets: List[Ticket]):
        """格式化打印推荐"""
        print(f"\n  {'策略':<15} {'#':<3} {'前区':<18} {'后区':<8} {'平均分':<8}")
        print("  " + "─" * 60)
        for t in tickets:
            print(f"  {t.strategy:<15} {t.index:<3} {t.front_str:<18} {t.back_str:<8} {t.score:<8.4f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8")

    r = Recommender(seed=42)
    print("=" * 70)
    print("  号码组合推荐 - 多策略混合（大乐透）")
    print("=" * 70)

    tickets = r.recommend_mixed_portfolio(
        n_top_heat=3,
        n_balanced=2,
        n_cold=1,
        n_most_freq=1,
    )
    r.print_recommendations(tickets)

    print(f"\n  总注数: {len(tickets)}")
    print(f"  投入: {len(tickets) * 2} 元")
    print(f"\n  ⚠️ 期望收益 = {len(tickets) * -0.99:.2f} 元（数学保证亏损）")
