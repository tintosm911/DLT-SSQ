"""
号码实战评估器 (基于 pick_advisor 核心库)
===========================================
让你选几组号码, 系统基于真实历史开奖数据给出真实评判。

四种玩法:
  A. check : 历史期验证 — 告诉期号 + 你当时的选号, 系统查那期真实开奖,
                  告诉你: 命中几等奖 + 真实奖金
  B. score : 任意号码的算法评分 (基于最新 N 期数据)
  C. oracle: 历史回测 — 用真实开奖号验证"完美预测"的命中率 (sanity check)
  D. live  : 上手即用 — 用最新一期做反查, 适合"我突然想到一组号"场景

所有玩法都共用 data.pick_advisor 库, Web / Desktop GUI 后续直接调这个库。

用法示例:
  # A. 历史期验证 (推荐)
  python scripts/evaluate_picks.py check --game dlt --period 26119 --front 3 6 20 24 32 --back 4 7
  python scripts/evaluate_picks.py check --game dlt --period 26118 --front 2 9 21 26 32 --back 6 12
  python scripts/evaluate_picks.py check --game ssq --period 2026119 --front 12 22 23 25 27 30 --back 4

  # B. 任意号码的算法评分
  python scripts/evaluate_picks.py score --game dlt --front 5 10 15 25 30 --back 3 8

  # C. 历史回测 (oracle)
  python scripts/evaluate_picks.py oracle --game dlt --last 100
  python scripts/evaluate_picks.py oracle --game ssq --last 50

  # D. 上手即用 (不指定 period 也行 — 默认用最新一期)
  python scripts/evaluate_picks.py live --game dlt --front 3 6 20 24 32 --back 4 7

  所有子命令都支持 --save / --note 持久化到 data-raw/my_picks.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'third_party'))

# 终端编码保护
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import get_game
from data.pick_advisor import (
    Pick, PickAdvisor, PickHistory, DataSnapshot,
)


HISTORY_PATH = PROJECT_ROOT / 'data-raw' / 'my_picks.csv'


# ============================================================
# 格式化输出
# ============================================================
def _format_result(r) -> str:
    """把 AssessResult 渲染成可读文本"""
    lines = []
    p = r.pick
    lines.append(f'  选号: 前 {p.front} / 后 {p.back}'
                 + (f'   (备注: {p.label})' if p.label else ''))
    lines.append(f'  期望奖金: {r.expected_prize:.4f} 元/注  |  净收益: {r.expected_net:+.4f} 元/注  |  凯利 f*={r.kelly_fraction:.3f}')
    lines.append(f'  一等奖概率: 1/{int(1/r.first_prize_odds):,}')
    lines.append(f'  建议: {r.recommendation}  {r.verdict_label}')

    if r.actual_draw:
        lines.append('')
        lines.append(f'  --- 历史反查 ---')
        lines.append(f'  期号 {r.actual_draw.get("period")} ({r.actual_draw.get("draw_date","")}) '
                     f'开奖: 前 {r.actual_draw.get("front")} / 后 {r.actual_draw.get("back")}')
        lines.append(f'  命中: {r.hit_prize}  |  前{r.hit_count.get("前区命中",0)}/后{r.hit_count.get("后区命中",0)} '
                     f'|  奖金: {r.win_money:,.0f} 元')

    if r.algo_scores:
        lines.append('')
        lines.append(f'  --- 7 算法百分位评分 ---')
        front_str = ' / '.join(f'{n}={r.avg_score.get(n,50):.0f}' for n in sorted(p.front))
        back_str = ' / '.join(f'{n}={r.avg_score.get(n,50):.0f}' for n in sorted(p.back))
        lines.append(f'  前区: {front_str}')
        lines.append(f'  后区: {back_str}')
        if r.hot_nums:
            lines.append(f'  热号(≥70): {r.hot_nums}')
        if r.cold_nums:
            lines.append(f'  冷号(<30): {r.cold_nums}')

    if r.risk_warnings:
        lines.append('')
        lines.append(f'  --- 风险提示 ---')
        for w in r.risk_warnings:
            lines.append(f'  ! {w}')

    return '\n'.join(lines)


def _parse_pick(args) -> Pick:
    """从 argparse 参数构造 Pick"""
    return Pick(
        front=list(args.front),
        back=list(args.back),
        label=args.note or '',
    )


# ============================================================
# 子命令: check
# ============================================================
def cmd_check(args):
    """A 玩法: 历史期验证"""
    cfg = get_game(args.game)
    actual, history = DataSnapshot.from_period(args.game, args.period)
    pick = _parse_pick(args)
    advisor = PickAdvisor(args.game)
    result = advisor.assess(
        pick,
        period=args.period,
        actual_draw=actual,
        recent_history=history,
    )
    print(f'\n=== [A] 历史期验证  {args.game.upper()} 期号 {args.period} ===')
    print(_format_result(result))
    if args.save:
        PickHistory(HISTORY_PATH).add(result, note=f'check {args.period}')
        print(f'\n  [已记录] {HISTORY_PATH}')
    return 0


# ============================================================
# 子命令: score
# ============================================================
def cmd_score(args):
    """B 玩法: 任意号码的算法评分"""
    history = DataSnapshot.latest_history(args.game, n=args.window)
    pick = _parse_pick(args)
    advisor = PickAdvisor(args.game)
    result = advisor.assess(pick, period=f'(基于最近 {len(history)} 期)', recent_history=history)
    print(f'\n=== [B] 算法评分  {args.game.upper()}  (窗口 {len(history)} 期) ===')
    print(_format_result(result))
    if args.save:
        PickHistory(HISTORY_PATH).add(result, note=f'score (window={len(history)})')
        print(f'\n  [已记录] {HISTORY_PATH}')
    return 0


# ============================================================
# 子命令: oracle (完美预测基准)
# ============================================================
def cmd_oracle(args):
    """C 玩法: 拿真实开奖数据做控制实验 — 每期随机选 1 注看实际命中率"""
    from data.sqlite_storage import SQLiteStorage
    import random

    storage = SQLiteStorage()
    df = storage.load_dataframe(game=args.game)
    if df.empty:
        print('数据库为空, 请先跑 python main.py crawl --game all')
        return 1
    cfg = get_game(args.game)
    last_n = min(args.last, len(df))
    sub = df.tail(last_n).reset_index(drop=True)
    print(f'\n=== [C] Oracle  {args.game.upper()}  最近 {last_n} 期 ===')
    print(f'  每期随机选 1 注 (范围 1-{cfg.front_range} 前{cfg.front_count}, '
          f'1-{cfg.back_range} 后{cfg.back_count}), 看实际命中率。\n')

    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    n_total = 0
    n_zero = 0        # 未中奖
    prize_count = {}  # 奖级 → 次数
    total_stake = 0.0
    total_win = 0.0
    from data.pick_advisor import judge_prize as jp
    for _, row in sub.iterrows():
        actual_front = sorted(int(row[f'front_{i+1}']) for i in range(cfg.front_count))
        actual_back = sorted(int(row[f'back_{i+1}']) for i in range(cfg.back_count))
        # 随机选 1 注
        pick_f = sorted(rng.sample(range(1, cfg.front_range + 1), cfg.front_count))
        pick_b = sorted(rng.sample(range(1, cfg.back_range + 1), cfg.back_count))
        prize, money = jp(args.game, Pick(front=pick_f, back=pick_b),
                          actual_front, actual_back)
        n_total += 1
        total_stake += 2.0
        total_win += money
        if money == 0:
            n_zero += 1
        else:
            prize_count[prize] = prize_count.get(prize, 0) + 1

    print(f'  期数: {n_total}')
    print(f'  未中奖: {n_zero}/{n_total} ({n_zero/n_total*100:.1f}%)')
    if prize_count:
        for k in sorted(prize_count.keys()):
            print(f'  {k}: {prize_count[k]} 次')
    print(f'  注金合计: {total_stake:.0f} 元  |  奖金合计: {total_win:,.0f} 元')
    print(f'  净收益: {total_win - total_stake:+,.0f} 元')
    print(f'  说明: 随机选号是"理论基线", 算法优化号码希望接近此分布, 不应差太远。')
    return 0


# ============================================================
# 子命令: live
# ============================================================
def cmd_live(args):
    """D 玩法: 上手即用 — 默认用最新一期做反查"""
    cfg = get_game(args.game)
    pick = _parse_pick(args)
    advisor = PickAdvisor(args.game)

    # 拿最新一期
    from data.sqlite_storage import SQLiteStorage
    storage = SQLiteStorage()
    df = storage.load_dataframe(game=args.game)
    if df.empty:
        print('数据库为空, 请先跑 python main.py crawl --game all')
        return 1

    latest = df.iloc[-1]
    actual_front = sorted(int(latest[f'front_{i+1}']) for i in range(cfg.front_count))
    actual_back = sorted(int(latest[f'back_{i+1}']) for i in range(cfg.back_count))
    actual = {
        'period': str(latest['period']),
        'draw_date': str(latest.get('draw_date', '')),
        'front': actual_front,
        'back': actual_back,
    }
    history = df.tail(max(args.window, 100))
    result = advisor.assess(pick, period=actual['period'], actual_draw=actual, recent_history=history)
    print(f'\n=== [D] Live  {args.game.upper()}  最近一期 {actual["period"]} ({actual["draw_date"]}) ===')
    print(_format_result(result))
    if args.save:
        PickHistory(HISTORY_PATH).add(result, note=f'live {actual["period"]}')
        print(f'\n  [已记录] {HISTORY_PATH}')
    return 0


# ============================================================
# 子命令: history (看我测过的号码)
# ============================================================
def cmd_history(args):
    """查看历史评估记录"""
    history = PickHistory(HISTORY_PATH)
    stats = history.stats()
    print(f'\n=== 历史评估记录 ({HISTORY_PATH}) ===')
    print(f'  测评次数: {stats["count"]}')
    print(f'  命中数: {stats["hits"]} ({stats.get("hit_rate", 0)*100:.1f}%)')
    if stats.get('total_stake'):
        print(f'  注金合计: {stats["total_stake"]:,.0f} 元')
        print(f'  奖金合计: {stats["total_win"]:,.0f} 元')
        print(f'  净收益: {stats["net_profit"]:+,.0f} 元 (ROI {stats["roi"]:+.1f}%)')
    return 0


# ============================================================
# CLI 主入口
# ============================================================
def build_parser():
    p = argparse.ArgumentParser(description='号码实战评估器 (基于 pick_advisor 库)')
    sub = p.add_subparsers(dest='cmd', required=True)

    def _add_common(sp):
        sp.add_argument('--game', choices=['dlt', 'ssq'], required=True, help='彩种: dlt=大乐透 / ssq=双色球')
        sp.add_argument('--front', type=int, nargs='+', required=True, help='前区号码 (5 或 6 个)')
        sp.add_argument('--back', type=int, nargs='+', required=True, help='后区号码 (2 或 1 个)')
        sp.add_argument('--note', default='', help='备注标签')
        sp.add_argument('--save', action='store_true', help='保存到 data-raw/my_picks.csv')

    # A
    pa = sub.add_parser('check', help='A. 历史期验证')
    _add_common(pa)
    pa.add_argument('--period', required=True, help='历史期号')
    pa.set_defaults(fn=cmd_check)

    # B
    pb = sub.add_parser('score', help='B. 任意号码的算法评分')
    _add_common(pb)
    pb.add_argument('--window', type=int, default=200, help='算法评分窗口 (默认 200 期)')
    pb.set_defaults(fn=cmd_score)

    # C
    pc = sub.add_parser('oracle', help='C. 控制实验: 每期随机选 1 注, 看真实命中率')
    pc.add_argument('--game', choices=['dlt', 'ssq'], required=True)
    pc.add_argument('--last', type=int, default=100, help='最近 N 期 (默认 100)')
    pc.add_argument('--seed', type=int, default=None, help='随机种子 (复现用)')
    pc.set_defaults(fn=cmd_oracle)

    # D
    pd = sub.add_parser('live', help='D. 上手即用 (默认反查最新一期)')
    _add_common(pd)
    pd.add_argument('--window', type=int, default=200, help='算法评分窗口')
    pd.set_defaults(fn=cmd_live)

    # history
    ph = sub.add_parser('history', help='查看历史评估记录')
    ph.set_defaults(fn=cmd_history, game='', front=[], back=[])

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 校验号码范围
    if args.cmd in ('check', 'score', 'live'):
        cfg = get_game(args.game)
        if len(args.front) != cfg.front_count:
            parser.error(f'{args.game} 前区需 {cfg.front_count} 个号码 (给了 {len(args.front)})')
        if len(args.back) != cfg.back_count:
            parser.error(f'{args.game} 后区需 {cfg.back_count} 个号码 (给了 {len(args.back)})')

    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main() or 0)
