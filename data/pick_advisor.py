"""
号码投注决策助手 (核心库)
=============================
把"评分 / 命中判定 / 历史对比"逻辑独立成可复用库,
CLI / Web / Desktop 三种入口都调用这里。

设计原则:
  - 纯函数: 输入 Pick, 输出 AssessResult
  - 无 I/O: 不读 CSV/JSON, 由调用方传入数据快照
  - 可序列化: 结果 dict 可直接 JSON 化给 Web 用
  - 无副作用: pick_history 只走 PickHistory 类管理

核心 API:
  PickAdvisor(game)               # 上下文: 知道彩种规则
  .assess(pick, *, period=None,   # 评审
          actual_draw=None,
          recent_history=None,
          algo_scores=None)
  → AssessResult (派奖金 / 命中率 / 算法分 / 建议)
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from data.games import get_game

# ============================================================
# 数据类
# ============================================================
@dataclass
class Pick:
    """一组选号"""
    front: List[int]
    back: List[int]
    label: str = ''           # 用户备注
    price: float = 2.0        # 单注金额

    def to_json(self) -> dict:
        return {'front': sorted(self.front), 'back': sorted(self.back),
                'label': self.label, 'price': self.price}


@dataclass
class AssessResult:
    """一次评估的完整结果"""
    pick: Pick
    game: str
    period: Optional[str]            # 历史期号 (如果有)

    # 期望值
    expected_prize: float = 0.0      # 期望奖金 (元)
    expected_net: float = -2.0       # 期望净收益 (元)
    ticket_price: float = 2.0
    kelly_fraction: float = 0.0      # 凯利 (0 = 不下注)
    first_prize_odds: float = 0.0    # 一等奖 1/N

    # 历史命中 (如有)
    actual_draw: Optional[Dict] = None  # {period, draw_date, front, back}
    hit_prize: str = '-'              # 几等奖 / "未中"
    hit_count: Dict[str, int] = field(default_factory=dict)   # {前/后, hit_num}
    win_money: float = 0.0            # 真实中奖金额

    # 算法评分 (如有)
    algo_scores: Dict[str, Dict[int, float]] = field(default_factory=dict)  # {algo: {num: pct}}
    avg_score: Dict[int, float] = field(default_factory=dict)   # 号码 → 7 算法平均分
    hot_nums: List[int] = field(default_factory=list)
    cold_nums: List[int] = field(default_factory=list)

    # 建议
    recommendation: str = ''          # '适合下注' / '不建议' / '纯娱乐'
    verdict_label: str = ''           # 短标签
    risk_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'pick': self.pick.to_json() if self.pick else None,
            'game': self.game,
            'period': self.period,
            'expected': {
                'prize_per_bet': self.expected_prize,
                'net_per_bet': self.expected_net,
                'kelly': self.kelly_fraction,
                'first_prize_odds': f'1/{int(1 / self.first_prize_odds):,}' if self.first_prize_odds else '?',
                'ticket_price': self.ticket_price,
            },
            'historical_hit': {
                'period': self.actual_draw.get('period') if self.actual_draw else None,
                'draw_date': self.actual_draw.get('draw_date') if self.actual_draw else None,
                'hit_prize': self.hit_prize,
                'hit_count': self.hit_count,
                'win_money': self.win_money,
            } if self.actual_draw else None,
            'algo_scores': self.algo_scores if self.algo_scores else None,
            'avg_score': {str(k): v for k, v in self.avg_score.items()} if self.avg_score else None,
            'recommendation': self.recommendation,
            'verdict_label': self.verdict_label,
            'warnings': self.risk_warnings,
        }


# ============================================================
# 奖级判定 (大乐透 + 双色球)
# ============================================================
def match_count(a: List[int], b: List[int]) -> int:
    return len(set(a) & set(b))


def judge_prize(game: str, pick: Pick,
                actual_front: List[int], actual_back: List[int]) -> Tuple[str, float]:
    """判定奖级 + 奖金"""
    f = match_count(pick.front, actual_front)
    b = match_count(pick.back, actual_back)

    if game == 'dlt':
        if f == 5 and b == 2:
            return '一等奖', 5_000_000
        if f == 5 and b == 1:
            return '二等奖', 300_000
        if f == 5 and b == 0:
            return '三等奖', 10_000
        if f == 4 and b == 2:
            return '四等奖', 3_000
        if f == 4 and b == 1:
            return '五等奖', 300
        if f == 3 and b == 2:
            return '六等奖', 200
        if f == 4 and b == 0:
            return '七等奖', 100
        if (f == 3 and b == 1) or (f == 2 and b == 2):
            return '八等奖', 15
        if (f == 3 and b == 0) or (f == 1 and b == 2) or (f == 2 and b == 1) or (f == 0 and b == 2):
            return '九等奖', 5
    else:  # ssq
        if f == 6 and b == 1:
            return '一等奖', 5_000_000
        if f == 6 and b == 0:
            return '二等奖', 150_000
        if f == 5 and b == 1:
            return '三等奖', 3_000
        if f == 5 and b == 0 or (f == 4 and b == 1):
            return '四等奖', 200
        if (f == 4 and b == 0) or (f == 3 and b == 1):
            return '五等奖', 10
        if (f == 3 and b == 0) or (f == 2 and b == 1) or (f == 1 and b == 1) or (f == 0 and b == 1):
            return '六等奖', 5

    return '未中', 0.0


# ============================================================
# 期望奖金计算
# ============================================================
def calc_expected_prize(game: str, pick: Pick) -> Tuple[float, float, float, float]:
    """
    计算单注期望奖金 + 期望净收益 + 凯利最优比例 + 一等奖概率.

    Returns: (expected_prize, expected_net, kelly_fraction, first_prize_odds)

    实现: 严格按 PrizeRules 算多变量超几何分布的期望.
    """
    from math import comb
    from data.games import get_game, get_prize_rules

    cfg = get_game(game)
    rules = get_prize_rules(game)
    fc = cfg.front_count
    fr = cfg.front_range
    bc = cfg.back_count
    br = cfg.back_range
    price = cfg.ticket_price

    if not rules:
        return 0.0, -price, 0.0, 0.0

    # 期望 = Σ (各奖级奖金 × 抽中该奖级的概率)
    # 概率自算: 不依赖规则里的 prob 字段 (其结构不稳定)
    # 数据要求: 玩家选了 fc 球 (买 1 注), 开奖是 fc 球独立等概率抽
    expected = 0.0
    for rule in rules:
        if not isinstance(rule, (tuple, list)) or len(rule) < 2:
            continue
        cond = rule[0]
        prize_info = rule[1]
        # 拿 money: 容错 tuple / int / 数字
        if isinstance(prize_info, (tuple, list)):
            money = prize_info[1] if len(prize_info) >= 2 else 0
        else:
            money = prize_info
        if not isinstance(money, (int, float)):
            continue

        # 多变量超几何概率 (前区命中 k, 后区命中 j)
        # P_f(k) = C(fc, k) × C(fr-fc, fc-k) / C(fr, fc)
        # P_b(j) = C(bc, j) × C(br-bc, bc-j) / C(br, bc)
        try:
            k, j = cond[0], cond[1]
            if k > fc or j > bc or k < 0 or j < 0:
                continue
            p_f = comb(fc, k) * comb(fr - fc, fc - k) / comb(fr, fc)
            p_b = comb(bc, j) * comb(br - bc, bc - j) / comb(br, bc)
            prob = p_f * p_b
        except Exception:
            continue
        expected += prob * money

    net = expected - price

    # 凯利 = (b*p - q) / b, b = 平均赔率 - 1
    # 用 (expected / price) 估算平均赔率
    if net <= 0:
        kelly = 0.0
    else:
        b = expected / price - 1.0
        kelly = max(0.0, min(1.0, (b * (expected / price) - (1 - expected / price)) / b)) if b > 0 else 0.0

    total_combos = comb(fr, fc) * comb(br, bc)
    prob_1 = 1.0 / total_combos

    return expected, net, kelly, prob_1


# ============================================================
# 算法评分 (热度百分位)
# ============================================================
def compute_algo_scores(game: str, recent_df, pick: Pick) -> Tuple[Dict, Dict]:
    """
    用 recent_df (DataFrame) 跑 7 算法, 给号码评分百分位.
    返回 (algo_scores, avg_score).

    algo_scores = { 'frequency': {1: pct, 2: pct, ...}, ... }
    avg_score = {号码: 7 算法平均百分位}
    """
    try:
        from core import compute_all_heat_scores
        import numpy as np
    except ImportError:
        return {}, {}

    cfg = get_game(game)
    if recent_df is None or len(recent_df) == 0:
        return {}, {}

    f_hi, b_hi = cfg.front_range, cfg.back_range
    front_onehot = np.zeros((len(recent_df), f_hi), dtype=int)
    back_onehot = np.zeros((len(recent_df), b_hi), dtype=int)

    for i, (_, row) in enumerate(recent_df.iterrows()):
        for j in range(cfg.front_count):
            n = int(row[f'front_{j+1}'])
            if 1 <= n <= f_hi:
                front_onehot[i, n - 1] = 1
        for j in range(cfg.back_count):
            n = int(row[f'back_{j+1}'])
            if 1 <= n <= b_hi:
                back_onehot[i, n - 1] = 1

    front_scores = compute_all_heat_scores(front_onehot, n_range=f_hi, window=min(50, len(recent_df)))
    back_scores = compute_all_heat_scores(back_onehot, n_range=b_hi, window=min(50, len(recent_df)))

    def to_pct(scores_dict, pick_nums):
        """转成百分位分 (0-100)"""
        out = {}
        for algo, scores in scores_dict.items():
            ranks = np.argsort(np.argsort(scores))
            n_max = len(scores)
            algo_pcts = {}
            for num in pick_nums:
                algo_pcts[num] = float(ranks[num - 1] / max(1, n_max - 1) * 100)
            out[algo] = algo_pcts
        return out

    front_algo = to_pct(front_scores, pick.front)
    back_algo = to_pct(back_scores, pick.back)

    # 拼成 {algo: {num: pct}} 形式 (flat dict for JSON)
    algo_scores_flat = {}
    for algo in front_algo:
        algo_scores_flat[algo] = front_algo[algo]
    for algo in back_algo:
        algo_scores_flat[f'{algo}_back'] = back_algo[algo]

    # 平均分
    avg_score = {}
    for num in pick.front:
        vals = [front_algo[a][num] for a in front_algo if num in front_algo[a]]
        avg_score[num] = round(sum(vals) / len(vals), 1) if vals else 50.0
    for num in pick.back:
        vals = [back_algo[a][num] for a in back_algo if num in back_algo[a]]
        avg_score[num] = round(sum(vals) / len(vals), 1) if vals else 50.0

    # 热/冷标记
    sorted_avg = sorted(avg_score.items(), key=lambda x: -x[1])
    hot = [n for n, v in sorted_avg if v >= 70]
    cold = [n for n, v in sorted_avg if v < 30]

    return algo_scores_flat, avg_score, hot, cold


# ============================================================
# 推荐评估 (核心函数)
# ============================================================
class PickAdvisor:
    """
    号码投注决策助手核心类.

    用法:
        from data.sqlite_storage import SQLiteStorage
        from data.pick_advisor import PickAdvisor, Pick

        storage = SQLiteStorage()
        df = storage.load_dataframe('dlt')

        advisor = PickAdvisor('dlt')
        result = advisor.assess(
            Pick(front=[3,6,20,24,32], back=[4,7]),
            period='26119',          # 必有
            actual_draw=...,
            recent_history=df.tail(100),
        )
        print(result.recommendation)
    """

    def __init__(self, game: str):
        self.game = game
        self.cfg = get_game(game)

    def assess(
        self,
        pick: Pick,
        *,
        period: Optional[str] = None,
        actual_draw: Optional[Dict] = None,
        recent_history=None,
    ) -> AssessResult:
        """
        综合评估.

        period: 用于"如果这期开奖"的指示 (不当 actual_front/actual_back 用)
        actual_draw: {period, draw_date, front, back} (历史开奖结果, 用于反查)
        recent_history: pd.DataFrame, 最近 N 期数据 (用于算法评分)
        """
        result = AssessResult(pick=pick, game=self.game, period=period,
                              ticket_price=self.cfg.ticket_price)

        # 1. 期望值
        exp_prize, exp_net, kelly, prob_1 = calc_expected_prize(self.game, pick)
        result.expected_prize = exp_prize
        result.expected_net = exp_net
        result.kelly_fraction = kelly
        result.first_prize_odds = prob_1

        # 2. 历史命中反查
        if actual_draw:
            result.actual_draw = actual_draw
            f_hit = match_count(pick.front, actual_draw.get('front', []))
            b_hit = match_count(pick.back, actual_draw.get('back', []))
            prize, money = judge_prize(self.game, pick,
                                       actual_draw.get('front', []),
                                       actual_draw.get('back', []))
            result.hit_prize = prize
            result.hit_count = {'前区命中': f_hit, '后区命中': b_hit}
            result.win_money = money

        # 3. 算法评分
        if recent_history is not None:
            algo_scores, avg_score, hot, cold = compute_algo_scores(
                self.game, recent_history, pick)
            result.algo_scores = algo_scores
            result.avg_score = avg_score
            result.hot_nums = hot
            result.cold_nums = cold

        # 4. 综合建议
        result.recommendation, result.verdict_label = self._make_recommendation(result)
        result.risk_warnings = self._make_warnings(result)

        return result

    def _make_recommendation(self, r: AssessResult) -> Tuple[str, str]:
        """生成建议"""
        if r.expected_net >= -0.05:
            # 接近收支平衡 (派奖率近 100% 的彩种理论)
            return '勉强平衡', '⚖ 弱正期望'
        if r.expected_net >= -0.50:
            return '纯娱乐 (亏损可控)', '○'
        if r.expected_net >= -1.0:
            return '纯娱乐 (数学亏损)', '○'
        return '强烈不建议', '❌ 不投'

    def _make_warnings(self, r: AssessResult) -> List[str]:
        w = []
        if r.expected_net < 0:
            w.append(f'期望净收益 {r.expected_net:+.2f} 元/注, 数学上必亏')
        if r.kelly_fraction <= 0:
            w.append(f'凯利最优 f*=0, 公式告诉你"不下注"')
        if r.hit_prize == '未中' and r.actual_draw:
            w.append(f'实际开奖: 前{r.hit_count.get("前区命中",0)}/{self.cfg.front_count}, 后{r.hit_count.get("后区命中",0)}/{self.cfg.back_count}, 未中奖')
        if r.cold_nums:
            w.append(f'冷号 {r.cold_nums} 命中率历史上略低于均匀')
        if r.first_prize_odds > 0:
            w.append(f'一等奖概率 1/{int(1/r.first_prize_odds):,}')
        # 学术诚信
        w.append('号码频率不能改变独立抽奖的理论概率 (DrawScope DISCLAIMER)')
        return w


# ============================================================
# 持久化: 我的号码历史
# ============================================================
class PickHistory:
    """记录用户测评过的号码 + 评估结果 (NDJSON 持久化, 每行一个完整 JSON 对象)"""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records: List[Dict] = []
        if self.path.exists():
            self._load()

    def _load(self):
        self.records = []
        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.records.append(json.loads(line))
                except json.JSONDecodeError:
                    # 兼容旧版 CSV 格式: 跳过有问题的行
                    continue

    def add(self, result: AssessResult, note: str = '') -> None:
        """记录一次评估"""
        d = result.to_dict()
        self.records.append({
            'timestamp': __import__('datetime').datetime.now().isoformat(),
            'note': note,
            **d,
        })
        self._save()

    def _save(self):
        if not self.records:
            return
        with open(self.path, 'w', encoding='utf-8') as f:
            for r in self.records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def stats(self) -> Dict:
        """统计历史记录"""
        if not self.records:
            return {'count': 0}
        n = len(self.records)
        hits = [r for r in self.records
                if r.get('historical_hit') and r['historical_hit'].get('win_money', 0) > 0]
        total_stake = n * 2.0
        total_win = sum(float(r['historical_hit'].get('win_money', 0))
                        for r in self.records if r.get('historical_hit'))
        return {
            'count': n,
            'hits': len(hits),
            'hit_rate': len(hits) / n if n else 0,
            'total_stake': total_stake,
            'total_win': total_win,
            'net_profit': total_win - total_stake,
            'roi': (total_win - total_stake) / total_stake * 100 if total_stake > 0 else 0,
        }


# ============================================================
# 数据快照辅助 (供 CLI/Web 直接调用)
# ============================================================
class DataSnapshot:
    """
    数据快照, 让 advisor 不必直接访问 storage.

    Usage:
        snap = DataSnapshot.from_period('dlt', '26119')
        result = advisor.assess(pick, period='26119', actual_draw=snap.actual, recent_history=snap.history)
    """

    @staticmethod
    def from_period(game: str, period: str, history_n: int = 200):
        from data.sqlite_storage import SQLiteStorage
        from data.games import get_game
        storage = SQLiteStorage()
        df = storage.load_dataframe(game=game)
        if df.empty:
            raise RuntimeError(f'数据库为空, 请先跑 python main.py crawl --game all')

        # 找这条 period
        match = df[df['period'] == period]
        if match.empty:
            raise ValueError(f'期号 {period} 不在数据库 (例如 26119)')

        cfg = get_game(game)
        actual = match.iloc[0].to_dict()
        actual['front'] = sorted([int(actual[f'front_{i+1}']) for i in range(cfg.front_count)])
        actual['back'] = sorted([int(actual[f'back_{i+1}']) for i in range(cfg.back_count)])
        actual['draw_date'] = str(actual.get('draw_date', ''))

        # 用这条之前的 N 期作为 algo 评分窗口
        idx = match.index[0]
        history = df.iloc[max(0, idx - history_n):idx]
        return actual, history

    @staticmethod
    def latest_history(game: str, n: int = 200):
        from data.sqlite_storage import SQLiteStorage
        storage = SQLiteStorage()
        df = storage.load_dataframe(game=game)
        if df.empty:
            raise RuntimeError('数据库为空')
        return df.tail(n)


__all__ = [
    'Pick',
    'AssessResult',
    'PickAdvisor',
    'PickHistory',
    'DataSnapshot',
    'judge_prize',
    'match_count',
    'calc_expected_prize',
    'compute_algo_scores',
]