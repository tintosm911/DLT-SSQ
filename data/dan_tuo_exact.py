"""
胆拖方案精确求解器
==================
用**精确超几何枚举**代替蒙特卡洛, 一次算出:
  - 每注奖金的精确概率分布 (零模拟误差)
  - 精确期望返奖 / 期望净收益
  - 精确「至少中一注」概率 (含各奖级)
  - 与 draw 无关, 只依赖组合结构 → 期望值是纯数学事实

原理
----
胆拖展开后, 前区是 C(t, k) 个组合 × 后区是 C(tb, kb) 个组合的笛卡尔积。
开奖时只需关心两个分类:
  前区: 胆码命中 df 个, 拖码池命中 J 个
  后区: 胆码命中 db 个, 拖码池命中 K 个
给定 (df, J), 我们挑的 4 个拖码里恰好命中 h 个的组合数 = C(J, h) * C(t-J, k-h);
后区同理。于是整张彩票的命中分布可以**完全枚举**出来, 不需要抽样。

口径与 data/pick_advisor.py::judge_prize 一致 (浮动奖取保底金额, 保守)。
一致性由 scripts/check_prize_consistency.py 保证。
"""
from __future__ import annotations

from math import comb
from typing import Dict, List, Tuple

from data.games import get_game, get_prize_rules


# ============================================================
# 奖级查表
# ============================================================
def _prize_lookup(game: str):
    """(前命中, 后命中) -> (奖级名, 奖金, 说明)"""
    table: Dict[Tuple[int, int], Tuple[str, float, str]] = {}
    for cond, info in get_prize_rules(game):
        label = info[0]
        money = float(info[1]) if isinstance(info, (tuple, list)) and len(info) > 1 else 0.0
        note = info[2] if isinstance(info, (tuple, list)) and len(info) > 2 else ''
        table[(int(cond[0]), int(cond[1]))] = (label, money, note)
    return table


# ============================================================
# 单区分类枚举
# ============================================================
def _zone_categories(n_dan: int, n_tuo: int, n_other: int,
                     draw_count: int) -> List[Tuple[int, int, int]]:
    """
    返回 [(dan_hit, tuo_pool_hit, other_hit), ...]
    对应开奖落在该分类下的**组合数**(未归一化)。
    """
    out = []
    for dan_hit in range(0, n_dan + 1):
        for pool_hit in range(0, n_tuo + 1):
            other_hit = draw_count - dan_hit - pool_hit
            if other_hit < 0 or other_hit > n_other:
                continue
            ways = comb(n_dan, dan_hit) * comb(n_tuo, pool_hit) * comb(n_other, other_hit)
            if ways:
                out.append((dan_hit, pool_hit, other_hit, ways))
    return out


def _hit_fracs(pool_hit: int, n_tuo: int, need: int) -> Dict[int, float]:
    """
    给定开奖命中拖码池 pool_hit 个, 我们从 n_tuo 个拖码里选 need 个,
    恰好命中 h 个的**比例**。
    """
    total = comb(n_tuo, need)
    out = {}
    for h in range(0, need + 1):
        c = comb(pool_hit, h) * comb(n_tuo - pool_hit, need - h)
        if c:
            out[h] = c / total
    return out


def _reachable_hits(pool_hit: int, n_tuo: int, need: int) -> List[int]:
    """
    我们选 need 个拖码时, 可能命中的个数 h 的**取值集合**。

    从 n_tuo 个拖码里选 need 个, 其中 pool_hit 个"在开奖里":
      h_min = max(0, need - (n_tuo - pool_hit))     # 全选不在开奖里的
      h_max = min(need, pool_hit)                   # 全选在开奖里的
    区间内每个值都可达 (组合论保证)。

    ★ 只依赖 pool_hit 的**个数**, 与具体是哪几个号无关 →
      所以给定开奖分类, 我们这套注能产生的命中数集合是确定的,
      "有没有注能中奖" 也是确定的 → 可以做**完全精确**的判定。
    """
    lo = max(0, need - (n_tuo - pool_hit))
    hi = min(need, pool_hit)
    return list(range(lo, hi + 1))


# ============================================================
# 主函数
# ============================================================
def exact_dan_tuo(game: str,
                  front_dan: List[int], front_tuo: List[int],
                  back_dan: List[int], back_tuo: List[int]) -> dict:
    """
    精确求解一个胆拖方案。

    Returns:
      n_bets / cost / n_front_combos / n_back_combos / need_front / need_back
      prize_dist  : [(奖级名, 奖金, 每注概率, 至少中一注该奖级的概率), ...]
      expected_return / expected_net / roi
      win_rate    : 至少中一注的概率 (%)
      lose_rate   : 全灭概率 (%)
      empty_prob  : 单注未中奖概率
      max_prize   : 单注最高奖金
    """
    cfg = get_game(game)
    lookup = _prize_lookup(game)

    front_dan = sorted(set(front_dan))
    front_tuo = sorted(set(front_tuo))
    back_dan = sorted(set(back_dan))
    back_tuo = sorted(set(back_tuo))

    need_f = cfg.front_count - len(front_dan)
    need_b = cfg.back_count - len(back_dan)
    if need_f < 0 or need_b < 0:
        raise ValueError('胆码数量超过该区选号上限')
    if need_f > len(front_tuo) or need_b > len(back_tuo):
        raise ValueError('拖码数量不足')

    n_f_combos = comb(len(front_tuo), need_f)
    n_b_combos = comb(len(back_tuo), need_b)
    n_bets = n_f_combos * n_b_combos
    cost = n_bets * cfg.ticket_price

    # --- 前区分类 ---
    f_other = cfg.front_range - len(front_dan) - len(front_tuo)
    f_cats = _zone_categories(len(front_dan), len(front_tuo), f_other, cfg.front_count)
    f_total = comb(cfg.front_range, cfg.front_count)
    f_prob = [(dh, ph, w / f_total) for dh, ph, _, w in f_cats]

    # --- 后区分类 ---
    b_other = cfg.back_range - len(back_dan) - len(back_tuo)
    b_cats = _zone_categories(len(back_dan), len(back_tuo), b_other, cfg.back_count)
    b_total = comb(cfg.back_range, cfg.back_count)
    b_prob = [(dh, ph, w / b_total) for dh, ph, _, w in b_cats]

    # --- 联合枚举 ---
    per_ticket: Dict[Tuple[int, int], float] = {}   # (nf, nb) -> 概率 (边际)
    level_any: Dict[Tuple[int, int], float] = {}     # (nf, nb) -> 至少中一注该奖级的概率
    level_prob: Dict[str, float] = {}               # 奖级名 -> 至少中一注该奖级的概率
    win_mass = 0.0
    expected_return = 0.0

    for dh_f, ph_f, pf in f_prob:
        ff = _hit_fracs(ph_f, len(front_tuo), need_f)
        f_reach = _reachable_hits(ph_f, len(front_tuo), need_f)
        for dh_b, ph_b, pb in b_prob:
            pj = pf * pb
            fb = _hit_fracs(ph_b, len(back_tuo), need_b)
            b_reach = _reachable_hits(ph_b, len(back_tuo), need_b)

            # ---- 本分类下, 这套注能产生的 (前命中, 后命中) 组合集合 ----
            reachable = []
            for m in (dh_f + h for h in f_reach):
                for n in (dh_b + k for k in b_reach):
                    reachable.append((m, n))

            # ---- 该分类下能否中奖 (完全确定的判定) ----
            hit_levels = {}
            for key in reachable:
                lvl = lookup.get(key)
                if lvl and lvl[1] > 0:
                    hit_levels[key] = lvl
            if hit_levels:
                win_mass += pj
                for key, lvl in hit_levels.items():
                    level_any[key] = level_any.get(key, 0.0) + pj
                # 同名奖级 (如九等奖对应 4 个 (m,n)) 在本分类内只算一次
                for lab in {lvl[0] for lvl in hit_levels.values()}:
                    level_prob[lab] = level_prob.get(lab, 0.0) + pj

            # ---- 期望返奖 (线性, 与结构无关; 但仍逐项累加便于核对) ----
            for hf, frac_f in ff.items():
                nf = dh_f + hf
                for hb, frac_b in fb.items():
                    nb = dh_b + hb
                    p = frac_f * frac_b
                    per_ticket[(nf, nb)] = per_ticket.get((nf, nb), 0.0) + pj * p
                    lvl = lookup.get((nf, nb))
                    if lvl and lvl[1] > 0:
                        expected_return += pj * p * lvl[1]

    lose_mass = 1.0 - win_mass

    # --- 每注奖级分布 (按奖级合并) ---
    detail_dist = []
    merged: Dict[str, dict] = {}
    for (nf, nb), p in per_ticket.items():
        lvl = lookup.get((nf, nb))
        label = lvl[0] if lvl else '未中'
        money = lvl[1] if lvl else 0.0
        detail_dist.append({
            'label': label, 'money': money, 'nf': nf, 'nb': nb,
            'prob_per_ticket': p,
            'prob_any': level_any.get((nf, nb), 0.0),
        })
        m = merged.setdefault(label, {
            'label': label, 'money': money, 'prob_per_ticket': 0.0,
        })
        m['prob_per_ticket'] += p
    for label, prob in level_prob.items():
        if label in merged:
            merged[label]['prob_any'] = prob
    merged.setdefault('未中', {'label': '未中', 'money': 0.0, 'prob_per_ticket': 0.0})
    merged['未中']['prob_any'] = lose_mass

    prize_dist = sorted(merged.values(), key=lambda x: -x['money'])
    detail_dist.sort(key=lambda x: (-x['money'], -x['prob_per_ticket']))
    empty_prob = sum(r['prob_per_ticket'] for r in prize_dist if r['money'] <= 0)

    max_prize = max((r['money'] for r in prize_dist), default=0.0)

    return {
        'game': game,
        'n_bets': n_bets,
        'cost': cost,
        'n_front_combos': n_f_combos,
        'n_back_combos': n_b_combos,
        'need_front': need_f,
        'need_back': need_b,
        'front_dan': front_dan, 'front_tuo': front_tuo,
        'back_dan': back_dan, 'back_tuo': back_tuo,
        'expected_return': expected_return * n_bets,
        'expected_net': expected_return * n_bets - cost,
        'roi': (expected_return * n_bets - cost) / cost if cost else 0.0,
        'win_rate': (1.0 - lose_mass) * 100,
        'lose_rate': lose_mass * 100,
        'empty_prob': empty_prob,
        'max_prize': max_prize,
        'prize_dist': prize_dist,
        'detail_dist': detail_dist,
    }


def fmt_scheme(r: dict) -> str:
    """一行摘要"""
    return (f"{r['n_bets']:>6,} 注 / {r['cost']:>7,.0f} 元 / "
            f"期望 {r['expected_net']:>+9,.0f} 元 / "
            f"中奖率 {r['win_rate']:>5.2f}%")
