"""
竞彩期望值分析 CLI
==================
用真实历史赔率 (football-data.co.uk 镜像) 回答:
**竞彩的期望值能不能是正的?**

用法:
  python scripts/sports_expectation.py                      # 默认英超全部缓存赛季
  python scripts/sports_expectation.py --league la-liga
  python scripts/sports_expectation.py --all-leagues
  python scripts/sports_expectation.py --chart
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.sports_odds import (CACHE_DIR, LEAGUE_DIRS, parse_season,
                              list_seasons, fetch_season_csv)
from data.sports_arb import (analyze_arb, analyze_vig, backtest_arbs,
                             backtest_random, backtest_value_bets,
                             run_full_analysis)

SEP = '=' * 78

# 只用真正独立的博彩公司 (排除 Max/Avg 这类聚合列)
REAL_BOOKS = ['B365', 'Pinnacle', 'WilliamHill', 'Betfair', 'VCBet',
              'Interwetten', 'Ladbrokes']


def load_cached(league: str):
    """加载本地缓存的所有赛季"""
    ms = []
    files = sorted(CACHE_DIR.glob(f'{league}_*.csv'))
    for f in files:
        try:
            ms.extend(parse_season(f.read_text(encoding='utf-8-sig')))
        except Exception:
            continue
    return ms, len(files)


def download(league: str, since: str = 'season-0506.csv'):
    """下载某联赛的赛季 (受 GitHub 限流影响, 已下载的走缓存)"""
    seasons = [s for s in list_seasons(league) if s >= since]
    ok = 0
    for s in seasons:
        if fetch_season_csv(league, s):
            ok += 1
    return ok


def main():
    ap = argparse.ArgumentParser(description='竞彩期望值分析')
    ap.add_argument('--league', default='premier-league',
                    help=f'联赛目录名, 可选: {", ".join(LEAGUE_DIRS)}')
    ap.add_argument('--all-leagues', action='store_true', help='分析所有已缓存联赛')
    ap.add_argument('--download', action='store_true', help='先下载数据')
    ap.add_argument('--chart', action='store_true', help='生成图表')
    ap.add_argument('--edge', type=float, default=0.03, help='价值下注 edge 门槛')
    args = ap.parse_args()

    leagues = list(LEAGUE_DIRS) if args.all_leagues else [args.league]

    if args.download:
        print('下载数据 (GitHub 限流, 已缓存的会跳过)...')
        for lg in leagues:
            print(f'  {lg}:')
            download(lg)

    all_matches = []
    print()
    for lg in leagues:
        ms, nfiles = load_cached(lg)
        if ms:
            print(f'  {LEAGUE_DIRS.get(lg, lg):<8} {len(ms):>6} 场  ({nfiles} 季缓存)')
            all_matches.extend(ms)

    if not all_matches:
        print('\n没有数据, 先跑 --download')
        return 1

    r = run_full_analysis(all_matches, books=REAL_BOOKS + ['Avg', 'Max'],
                          value_books=('Pinnacle', 'B365', 'Avg'))

    print()
    print(SEP)
    print(f'  竞彩期望值分析  —  {len(all_matches):,} 场真实历史赔率')
    print(SEP)
    print('  数据源: football-data.co.uk GitHub 镜像 (真实赔率, 非模拟)')
    print('  ⚠ 时效性: 数据为历史快照, 结论反映的是**历史市场结构**;')
    print('    当前市场是否仍然如此, 需要用当下赔率复验.')

    print()
    print('  【1】抽水率 (vig = Σ(1/odds) - 1) — 庄家优势')
    print(f'      {"公司":<14}{"均值":>9}{"中位":>9}{"最小":>9}{"最大":>9}{"场次":>9}')
    for k, v in sorted(r['vig'].items(), key=lambda x: x[1]['mean']):
        print(f'      {k:<14}{v["mean"]*100:>8.2f}%{v["median"]*100:>8.2f}%'
              f'{v["min"]*100:>8.2f}%{v["max"]*100:>8.2f}%{v["count"]:>9}')
    ranked = sorted(r['vig'].items(), key=lambda x: x[1]['mean'])
    if len(ranked) >= 2:
        gap = (ranked[-1][1]['mean'] - ranked[0][1]['mean']) * 100
        print(f'      → 最优 {ranked[0][0]} 与最差 {ranked[-1][0]} 相差 {gap:.2f} 个百分点')
        print(f'        (这是**真实可执行**的建议: 一直在最优公司下注)')

    print()
    print('  【2】跨公司套利 (Σ(1/odds) < 1 即锁定利润, 数学上必赢)')
    a = r['arb']
    print(f'      可套利场次: {a["count"]} / {a["checked"]} ({a["rate"]:.2f}%)')
    print(f'      最高锁定: {a["max_profit"]:.2f}%  平均: {a["mean_profit"]:.3f}%')
    bt = r.get('arb_backtest') or {}
    if bt.get('count'):
        print(f'      资金回测 (每场 100 元, 每天最多 5 次):')
        print(f'        下注 {bt["count"]} 次, 投入 {bt["stake"]:,.0f} 元, '
              f'返奖 {bt["returns"]:,.0f} 元')
        print(f'        净收益 {bt["net"]:+,.0f} 元,  ROI {bt["roi"]:+.3f}%')
    if a.get('best'):
        b = a['best']
        print(f'      最佳单笔: {b.date} {b.home} vs {b.away}')
        print(f'        组合 {" / ".join(b.books)}  赔率 {b.odds}')
        print(f'        Σ(1/o) = {b.sum_inv:.6f}  →  锁定 {b.profit_pct:.3f}%')
        for book, stake, ret in b.stake_plan(100):
            print(f'          {book:<14} 投入 {stake:>6.2f} 元  (中则返 {ret:.2f} 元)')

    print()
    print('  【3】价值下注 (Elo 模型 vs 赔率隐含概率, 严格 walk-forward)')
    print(f'      {"公司":<10}{"下注数":>8}{"ROI":>10}{"命中率":>9}{"CLV":>10}')
    for k, v in r['value_bets'].items():
        print(f'      {k:<10}{v.bets:>8}{v.roi:>+9.2f}%{v.hit_rate:>8.1f}%{v.clv:>+10.4f}')
    print('      (CLV = 收盘线价值: 正说明下注时拿到的价格比收盘更好)')

    print()
    print('  【4】随机下注基线 (直接体现抽水)')
    for k, v in r['random_baseline'].items():
        print(f'      {k:<10} ROI {v["roi"]:>+7.2f}%  (σ {v["std"]:.1f}%, n={v["n_matches"]})')

    print()
    print(SEP)
    print('  【结论】')
    for line in r['conclusion'].split(' | '):
        print(f'    • {line}')
    print()
    print('  与号码彩的根本区别:')
    print('    号码彩: 派奖率结构性低于 50%, 任何策略都改不了, f*=0')
    print('    竞彩:  ① 抽水让"无条件下注"必亏')
    print('          ② 但**跨公司套利是数学上必赢** (Σ(1/o)<1), 实测 ROI 为正')
    print('          ③ 选低抽水公司也能实打实省钱')
    print('          ④ 靠模型"预测比赛"赚钱很难 (Elo 打不过市场)')
    print(SEP)
    print()

    if args.chart:
        try:
            from scripts.make_sports_chart import make_chart
            out = make_chart(all_matches, r)
            print(f'图表: {out}')
        except Exception as e:
            print(f'图表生成失败: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
