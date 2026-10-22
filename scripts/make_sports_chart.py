"""
竞彩期望值图表
==============
三联图, 与号码彩门面图风格统一:

  左: 各博彩公司抽水率 (vig) — 选对公司就是实打实省钱
  中: 三种玩法 ROI 对比 (套利 / 价值下注 / 随机) — 只有套利是正的
  右: 套利机会分布 (多少场有套利 + 锁定多少利润)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

for _f in ('Microsoft YaHei', 'Noto Sans SC', 'SimHei'):
    if any(f.name == _f for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.sans-serif'] = [_f]
        break
plt.rcParams['axes.unicode_minus'] = False

REPORTS = PROJECT_ROOT / 'reports'
C_RED = '#dc2626'
C_GREEN = '#16a34a'
C_BLUE = '#2563eb'
C_AMBER = '#f59e0b'
C_DARK = '#0f172a'


def _style(ax):
    ax.set_facecolor('#f8fafc')
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#cbd5e1')
    ax.tick_params(colors='#475569', labelsize=9)
    ax.grid(axis='y', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def make_chart(matches, result, out=None):
    fig, axes = plt.subplots(1, 3, figsize=(19, 8.4))
    fig.patch.set_facecolor('white')
    fig.subplots_adjust(left=0.075, right=0.985, top=0.84, bottom=0.155,
                        wspace=0.30)

    # ---------- 左: 抽水率 ----------
    ax = axes[0]
    vig = sorted(result['vig'].items(), key=lambda x: x[1]['mean'])
    names = [k for k, _ in vig]
    means = [v['mean'] * 100 for _, v in vig]
    meds = [v['median'] * 100 for _, v in vig]
    lo = [v['min'] * 100 for _, v in vig]
    hi = [v['max'] * 100 for _, v in vig]
    y = np.arange(len(vig))
    colors = [C_GREEN if m < 3 else (C_AMBER if m < 6 else '#fca5a5')
              for m in means]
    ax.barh(y, means, color=colors, height=0.62, zorder=3,
            label='平均抽水')
    ax.errorbar(meds, y, xerr=[np.array(meds) - np.array(lo),
                               np.array(hi) - np.array(meds)],
                fmt='none', ecolor='#475569', elinewidth=1, capsize=3, zorder=4)
    ax.set_yticks(y)
    # Max/Avg 是聚合列 (各公司极值/均值), 不是能独立下注的公司
    ax.set_yticklabels([f'{n}  (聚合列)' if n in ('Max', 'Avg') else n
                        for n in names], fontsize=9)
    ax.set_xlabel('抽水率 %  (Σ(1/odds) - 1)', fontsize=9, color='#475569')
    ax.set_title('① 各博彩公司抽水率\n选对公司 = 实打实省钱', fontsize=11,
                 fontweight='bold', color=C_DARK, pad=10)
    if len(means) >= 2:
        gap = max(means) - min(means)
        ax.set_title(f'① 各博彩公司抽水率\n最优 vs 最差差 {gap:.2f} 个百分点',
                     fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    _style(ax)
    ax.grid(axis='x', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.grid(axis='y', visible=False)

    # ---------- 中: 三种玩法 ROI ----------
    ax = axes[1]
    rows = []
    bt = result.get('arb_backtest') or {}
    if bt.get('count'):
        rows.append(('跨公司套利\n(数学上必赢)', bt['roi'], C_GREEN))
    for k, v in result['value_bets'].items():
        rows.append((f'Elo 价值下注\n{k}', v.roi, '#fca5a5'))
    for k, v in result['random_baseline'].items():
        rows.append((f'随机下注\n{k}', v['roi'], '#94a3b8'))
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    cols = [r[2] for r in rows]
    x = np.arange(len(rows))
    ax.bar(x, vals, color=cols, width=0.55, zorder=3)
    ax.axhline(0, color=C_DARK, linewidth=1.4, zorder=4)
    for i, v in enumerate(vals):
        ax.text(i, v + (0.6 if v >= 0 else -1.2),
                f'{v:+.2f}%', ha='center', fontsize=9.5, fontweight='bold',
                color=C_GREEN if v >= 0 else C_RED, zorder=5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5, rotation=20, ha='right',
                       rotation_mode='anchor')
    ax.set_ylabel('ROI %', fontsize=9, color='#475569')
    ax.set_title('② 三种玩法实测 ROI\n只有"套利"是正的 — 但不靠预测',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    span = max(abs(min(vals)), abs(max(vals))) or 5
    ax.set_ylim(min(vals) - span * 0.35, max(vals) + span * 0.35)
    _style(ax)

    # ---------- 右: 套利机会分布 ----------
    ax = axes[2]
    a = result['arb']
    if a.get('arbs'):
        profits = np.array([x.profit_pct for x in a['arbs']])
        bins = [0, 0.5, 1, 2, 3, 4, 5, 100]
        cnt = [int(((profits >= bins[i]) & (profits < bins[i + 1])).sum())
               for i in range(len(bins) - 1)]
        lbls = ['0-0.5%', '0.5-1%', '1-2%', '2-3%', '3-4%', '4-5%', '≥5%']
        cols = ['#86efac', '#4ade80', '#22c55e', C_AMBER, '#fb923c',
                C_RED, '#991b1b']
        ax.bar(range(len(cnt)), cnt, color=cols, width=0.68, zorder=3)
        for i, c in enumerate(cnt):
            if c:
                ax.text(i, c + max(cnt) * 0.02, str(c), ha='center',
                        fontsize=9, color='#334155')
        ax.set_xticks(range(len(lbls)))
        ax.set_xticklabels(lbls, fontsize=8)
        ax.set_ylabel('场次', fontsize=9, color='#475569')
        ax.set_title(f'③ 套利机会分布\n{a["count"]} / {a["checked"]} 场可套利 '
                     f'({a["rate"]:.1f}%)', fontsize=11, fontweight='bold',
                     color=C_DARK, pad=10)
        _style(ax)
        ax.text(0.5, 0.94,
                f'每次锁定利润中位 {a["median_profit"]:.2f}%\n'
                f'最高 {a["max_profit"]:.2f}%',
                transform=ax.transAxes, ha='center', va='top', fontsize=9.5,
                fontweight='bold', color=C_GREEN,
                bbox=dict(boxstyle='round,pad=0.45', fc='white',
                          ec=C_GREEN, lw=1.2, alpha=0.95))
        ax.set_ylim(0, max(cnt) * 1.22)
    else:
        ax.text(0.5, 0.5, '未发现套利机会', ha='center', va='center',
                fontsize=13, color='#94a3b8', transform=ax.transAxes)
        ax.set_title('③ 套利机会分布', fontsize=11, fontweight='bold',
                     color=C_DARK, pad=10)
        _style(ax)

    # 标题 + 结论条
    fig.suptitle('竞彩期望值实证检验  —  这次, 数学站在你这边',
                 fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             f'基于 {len(matches):,} 场真实历史赔率 (football-data.co.uk) · '
             f'每项都跟随机/抽水基准对比',
             ha='center', fontsize=11, color='#64748b')

    bt = result.get('arb_backtest') or {}
    bt_txt = (f'套利资金回测 ROI {bt["roi"]:+.2f}%'
              if bt.get('count') else '套利: 无')
    fig.text(0.5, 0.042,
             f'结论:  ① 抽水 {min(v["mean"] for _, v in vig)*100:.1f}%~'
             f'{max(v["mean"] for _, v in vig)*100:.1f}%, 选对公司就省钱    '
             f'② {bt_txt}  ← 数学上必赢    '
             f'③ Elo 价值下注打不过市场    '
             f'→  竞彩能赢, 但赢在**市场结构**, 不在**预测能力**',
             ha='center', fontsize=11, color='white', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.65', fc=C_DARK, ec='none'))

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = out or (REPORTS / 'headline_sports.png')
    fig.savefig(out, dpi=145, bbox_inches='tight', facecolor='white',
                pad_inches=0.3)
    plt.close(fig)
    return out


if __name__ == '__main__':
    from data.sports_odds import parse_season, CACHE_DIR
    from data.sports_arb import run_full_analysis
    from scripts.sports_expectation import REAL_BOOKS, load_cached

    ms = []
    for lg in ('premier-league', 'la-liga', 'serie-a', 'bundesliga',
               'ligue-1'):
        m, _ = load_cached(lg)
        ms.extend(m)
    if not ms:
        print('没有缓存数据')
        sys.exit(1)
    r = run_full_analysis(ms, books=REAL_BOOKS + ['Avg', 'Max'],
                          value_books=('Pinnacle', 'B365', 'Avg'))
    print(f'已生成: {make_chart(ms, r)}  ({len(ms)} 场)')
