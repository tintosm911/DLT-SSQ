"""
联合全灭概率 —— 事前算清"这次全灭有多罕见"
=============================================
★ 核心问题:
  实战结算时最容易犯的错, 是事后用"运气不好"解释一切。
  本脚本给出**事前**就能算出来的答案:
  "我这三套方案同时全灭的概率, 到底是多少?"

★ 为什么必须全枚举:
  同一期买的多套方案**共用号码池** → 不独立,
  把各自的全灭概率相乘会严重低估 (实测 7.05% vs 真实 91.17%)。
  只能对全部 C(35,5) x C(12,2) = 21,425,712 种开奖组合逐个判定。

★ 两条独立算法互相验证:
  本脚本 (numpy 全枚举) 的单套全灭概率
  vs data/dan_tuo_exact.py (组合数解析解) 的 lose_rate
  → 两者必须逐位吻合, 否则有一方算错了。

用法:
  python scripts/joint_miss_prob.py                  # 最近一期已结算的实买方案
  python scripts/joint_miss_prob.py --period 2026135
  python scripts/joint_miss_prob.py --all            # 所有已结算期
"""
from __future__ import annotations

import argparse
import sys
import time
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np

from data.games import normalize_period
from data.dan_tuo_exact import exact_dan_tuo


def win_cond(f, b):
    """前区命中 f、后区命中 b → 是否中奖 (大乐透奖级表)"""
    if f >= 3:
        return True
    if f == 2 and b >= 1:
        return True
    if f == 1 and b == 2:
        return True
    if f == 0 and b == 2:
        return True
    return False


def build_tickets(p):
    out = []
    for fc in combinations(p['front_tuo'], 5 - len(p['front_dan'])):
        for bc in combinations(p['back_tuo'], 2 - len(p['back_dan'])):
            out.append((tuple(sorted(list(p['front_dan']) + list(fc))),
                        tuple(sorted(list(p['back_dan']) + list(bc)))))
    return out


def analyse(period, plans, draw_front=None, draw_back=None):
    """
    plans: {label: {front_dan, front_tuo, back_dan, back_tuo}}
    返回统计字典
    """
    t0 = time.time()
    front = np.array(list(combinations(range(1, 36), 5)), dtype=np.int8)
    back = np.array(list(combinations(range(1, 13), 2)), dtype=np.int8)
    NF, NB = len(front), len(back)

    cnt = np.zeros((NF, 35), dtype=np.int8)
    for i in range(5):
        cnt[np.arange(NF), front[:, i] - 1] = 1
    cntb = np.zeros((NB, 12), dtype=np.int8)
    for i in range(2):
        cntb[np.arange(NB), back[:, i] - 1] = 1

    plan_f, plan_b = {}, {}
    for name, p in plans.items():
        tk = build_tickets(p)
        F = np.empty((len(tk), NF), dtype=np.int8)
        for j, (fr, _b) in enumerate(tk):
            F[j] = cnt[:, [x - 1 for x in fr]].sum(axis=1)
        B = np.empty((len(tk), NB), dtype=np.int8)
        for j, (_f, bk) in enumerate(tk):
            B[j] = cntb[:, [x - 1 for x in bk]].sum(axis=1)
        plan_f[name], plan_b[name] = F, B

    labels = list(plans)
    per_plan = {n: 0 for n in labels}
    joint = 0

    for bi in range(NB):
        miss_list = []
        for name in labels:
            F = plan_f[name].astype(np.int16)
            B = plan_b[name][:, bi].astype(np.int16)[:, None]
            win = ((F >= 3) | ((F == 2) & (B >= 1))
                   | ((F == 1) & (B >= 2)) | ((F == 0) & (B >= 2)))
            miss = ~win.any(axis=0)
            miss_list.append(miss)
            per_plan[name] += int(miss.sum())
        # ★ 联合: 必须是**同一个开奖号** (同一前区组合 + 同一后区组合) 下
        #   三个方案同时全灭。旧写法用 `all_miss[name] |= miss` 跨后区组合
        #   累积 OR, 等价于"三个方案各自挑了不同的后区组合" → 结果虚高。
        j = miss_list[0]
        for m in miss_list[1:]:
            j = j & m
        joint += int(j.sum())

    total = NF * NB
    # 独立假设下的对照
    indep = 1.0
    for n in labels:
        indep *= per_plan[n] / total

    # ★ 自检: 联合全灭 ⊆ 每一套的单套全灭, 所以联合全灭率必须 ≤ 最小单套全灭率。
    #   (旧实现跨后区组合累积 OR, 得出 91.17% > 27.59% —— 数学上不可能)
    joint_pct = joint / total * 100
    min_single = min(per_plan[n] / total * 100 for n in labels)
    assert joint_pct <= min_single + 1e-9, (
        f'联合全灭 {joint_pct:.4f}% > 最小单套全灭 {min_single:.4f}% '
        f'→ 联合逻辑有 bug')

    # 真实开奖号在枚举中的位置
    rank = None
    if draw_front and draw_back:
        fi = bi_ = None
        for i, row in enumerate(front):
            if list(row) == list(draw_front):
                fi = i
                break
        for i, row in enumerate(back):
            if list(row) == list(draw_back):
                bi_ = i
                break
        if fi is not None and bi_ is not None:
            rank = fi / NF * 100

    return {
        'period': period,
        'n_plans': len(labels),
        'total_combos': total,
        'per_plan_miss': per_plan,
        'per_plan_miss_pct': {n: per_plan[n] / total * 100 for n in labels},
        'joint_miss': joint,
        'joint_miss_pct': joint / total * 100,
        'indep_pct': indep * 100,
        'rank_pct': rank,
        'seconds': time.time() - t0,
    }


def main():
    ap = argparse.ArgumentParser(description='联合全灭概率 (全枚举)')
    ap.add_argument('--period', default='', help='期号 (7位), 默认最近一期')
    ap.add_argument('--all', action='store_true', help='所有已结算期')
    ap.add_argument('--plans', default='', help='逗号分隔的方案 label, '
                                                 '默认取全部实买方案')
    args = ap.parse_args()

    from scripts.verify_live_picks import (load_archive, load_ledger,
                                           load_purchased, split_real_paper,
                                           official_dlt_map)
    ledger = load_ledger()
    if not ledger:
        print('  账本为空, 没有已结算的期')
        return 0
    purchased = load_purchased()
    real, paper = split_real_paper(ledger, purchased)
    rows = real or ledger

    periods = sorted({normalize_period(str(r.get('target_period', '')), 'dlt')
                      for r in rows})
    if args.period:
        periods = [normalize_period(args.period, 'dlt')]
    elif not args.all:
        periods = periods[-1:]

    archive = load_archive()
    try:
        draws = official_dlt_map(30)
    except Exception as e:
        draws = {}
        print(f'  [warn] 拉开奖失败: {e}')

    for period in periods:
        prows = [r for r in rows
                 if normalize_period(str(r.get('target_period', '')), 'dlt')
                 == period]
        if args.plans:
            want = {s.strip() for s in args.plans.split(',')}
            prows = [r for r in prows if r.get('label') in want]
        if not prows:
            continue

        plans = {}
        for r in prows:
            for a in archive:
                # ★ 期号 + ts + label **三者都要对上**:
                #   同一期批量生成的 A/B/C 三套 ts 完全相同, 只按 ts 匹配会
                #   让三套全部拿到 A 版的结构 (算出来的全灭概率一模一样)。
                if (normalize_period(str(a.get('target_period', '')), 'dlt')
                        == period
                        and str(a.get('ts', '')) == str(r.get('ts', ''))
                        and (a.get('label') or '') == (r.get('label') or '')):
                    plans[r.get('label') or '(未标注)'] = {
                        'front_dan': a.get('front_dan') or [],
                        'front_tuo': a.get('front_tuo') or [],
                        'back_dan': a.get('back_dan') or [],
                        'back_tuo': a.get('back_tuo') or [],
                    }
                    break
        if not plans:
            continue

        d = draws.get(period)
        df = list(d[1]) if d else None
        db = list(d[2]) if d else None

        print()
        print('=' * 78)
        print(f'  联合全灭概率 · 期号 {period}')
        print('=' * 78)
        if d:
            print(f'  开奖号: 前区 {" ".join(f"{v:02d}" for v in df)}'
                  f' + 后区 {" ".join(f"{v:02d}" for v in db)}')
        print(f'  参与方案 {len(plans)} 套')

        res = analyse(period, plans, df, db)

        print(f'\n  全枚举 C(35,5) x C(12,2) = {res["total_combos"]:,} '
              f'种开奖组合  ({res["seconds"]:.1f}s)')
        print('\n  ── 单套全灭概率 (全枚举 vs 解析解) ──')
        for name in plans:
            enum_pct = res['per_plan_miss_pct'][name]
            p = plans[name]
            exact = exact_dan_tuo('dlt', front_dan=p['front_dan'],
                                  front_tuo=p['front_tuo'],
                                  back_dan=p['back_dan'],
                                  back_tuo=p['back_tuo'])
            ok = '✅ 一致' if abs(enum_pct - exact['lose_rate']) < 0.01 else '❌ 不一致'
            print(f'    {name:<22} 全灭 {enum_pct:7.4f}%  '
                  f'| 解析解 {exact["lose_rate"]:7.4f}%  {ok}')

        print('\n  ── 全部方案同时全灭 (联合, 非独立) ──')
        print(f'    联合全灭概率 {res["joint_miss_pct"]:.4f}%  '
              f'(1 / {res["total_combos"] / max(res["joint_miss"], 1):,.0f})')
        print(f'    若假设独立相乘 = {res["indep_pct"]:.4f}%  '
              f'← **错误估计**: 方案共用号码池, 高度相关')

        if res['rank_pct'] is not None:
            print(f'\n  本期开奖号在前区组合里处于第 {res["rank_pct"]:.2f} '
                  f'百分位 → 开奖号本身是随机的, 谈不上"选号有没有中"')
        print()

    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
