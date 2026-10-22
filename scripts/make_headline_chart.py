"""
门面图生成器
============
把三个工具的核心结论画成一张三联图:

  左: 13 种策略的 ROI vs 随机基线 (全部在 -70% ~ -83%, 无一转正)
  中: 中奖率缺口 (最好 7.94% vs 盈亏平衡 40%, 差 5 倍)
  右: 热号预测力 (各年份切分的 z 分数, 全在 ±2 内 = 与随机无差异)

用法:
  python scripts/make_headline_chart.py
  python scripts/make_headline_chart.py --game ssq
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

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

# --- 中文字体 ---
for _f in ('Microsoft YaHei', 'Noto Sans SC', 'SimHei'):
    if any(f.name == _f for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.sans-serif'] = [_f]
        break
plt.rcParams['axes.unicode_minus'] = False

REPORTS = PROJECT_ROOT / 'reports'

# 配色
C_RED = '#dc2626'
C_GREEN = '#16a34a'
C_BLUE = '#2563eb'
C_AMBER = '#f59e0b'
C_GRAY = '#94a3b8'
C_DARK = '#0f172a'


def _style_ax(ax):
    ax.set_facecolor('#f8fafc')
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#cbd5e1')
    ax.tick_params(colors='#475569', labelsize=9)
    ax.grid(axis='y', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def panel_strategies(ax, game, lab):
    """左图: 各策略 ROI vs 随机基线"""
    from data.strategy_lab import run_lab
    r = run_lab(game, window=200, start=max(500, r_start(game)),
                n_seeds=10)
    ss = sorted(r['strategies'], key=lambda x: x['roi_ex_big'])
    names = [s['name'] for s in ss]
    # ⚠ 主条形用"剔除大奖后的 ROI" —— 否则一次二等奖就能把曲线拉成正的,
    #   那是最容易误导人的画面
    rois = [s['roi_ex_big'] for s in ss]
    wrs = [s['win_rate'] for s in ss]
    raws = [s['roi'] for s in ss]
    bigs = [s['big_prizes'] for s in ss]

    colors = []
    for s in ss:
        if s['name'] == 'random':
            colors.append(C_BLUE)
        elif s['big_prizes'] > 0:
            colors.append(C_AMBER)
        else:
            colors.append('#fca5a5')

    y = np.arange(len(ss))
    ax.barh(y, rois, color=colors, height=0.68, zorder=3)
    ax.axvline(0, color=C_DARK, linewidth=1.4, zorder=4)

    b = r['baseline']
    ax.axvline(b['roi_ex_big_mean'], color=C_BLUE, linestyle='--', linewidth=1.6,
               zorder=5, label=f'随机基线均值 {b["roi_ex_big_mean"]:.1f}%')
    ax.axvspan(b['roi_ex_big_mean'] - b['roi_ex_big_std'],
               b['roi_ex_big_mean'] + b['roi_ex_big_std'],
               color=C_BLUE, alpha=0.12, zorder=1,
               label=f'随机基线 ±1σ ({b["roi_ex_big_std"]:.1f}%)')

    labels = []
    for s, wr, raw, big in zip(ss, wrs, raws, bigs):
        marks = ''
        if s['name'] == 'random':
            marks += '★'
        if big:
            marks += '◆'
        labels.append(f'{s["name"]} (中奖率{wr:.1f}%){marks}')
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.set_xlabel('ROI %  (每 100 元投入的总回报, 已剔除大奖)', fontsize=9,
                  color='#475569')
    ax.set_title(f'① 13 种选号策略的真实 ROI\n{lab} · {r["tested_draws"]} 期 walk-forward 回测',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)

    from matplotlib.patches import Patch
    handles = [
        Patch(fc=C_BLUE, label='随机基线 (对照)'),
        Patch(fc=C_AMBER, label='◆ 该策略中了大奖 (原始 ROI 被拉高)'),
        Patch(fc='#fca5a5', label='未中大奖的策略'),
        plt.Line2D([0], [0], color=C_BLUE, ls='--', lw=1.6,
                   label=f'随机基线均值 {b["roi_ex_big_mean"]:.1f}%'),
    ]
    ax.legend(handles=handles, fontsize=7.5, loc='lower right', framealpha=0.92)

    # 标注含大奖策略的原始 ROI (clamp 到图内)
    x_lo, x_hi = min(rois) - 14, max(8, max(rois) + 8)
    for i, (s, raw, big) in enumerate(zip(ss, raws, bigs)):
        if big:
            tx = min(max(raw, x_lo + 2), x_hi - 12)
            ax.text(tx, i + 0.34, f'原始 {raw:+.0f}%', va='center', fontsize=7,
                    color=C_AMBER, fontweight='bold')

    ax.set_xlim(x_lo, x_hi)
    _style_ax(ax)
    ax.grid(axis='x', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.grid(axis='y', visible=False)
    return r


def r_start(game):
    from data.sqlite_storage import SQLiteStorage
    n = len(SQLiteStorage().load_dataframe(game))
    return max(500, n // 3)


def panel_winrate(ax, game, lab, strat_result):
    """中图: 中奖率缺口"""
    from data.strategy_lab import breakeven_win_rate
    be = breakeven_win_rate(game)
    ss = strat_result['strategies']
    names = [s['name'] for s in ss]
    wrs = [s['win_rate'] for s in ss]
    base_wr = strat_result['baseline']['win_rate_mean']

    order = np.argsort(wrs)
    names = [names[i] for i in order]
    wrs = [wrs[i] for i in order]

    x = np.arange(len(wrs))
    colors = [C_AMBER if w >= base_wr else '#fcd34d' for w in wrs]

    ax.bar(x, wrs, color=colors, width=0.68, zorder=3,
           edgecolor='none')
    ax.axhline(base_wr, color=C_BLUE, linestyle='--', linewidth=1.6,
               zorder=5, label=f'随机基线 {base_wr:.2f}%')
    ax.axhline(be['breakeven_at_lowest'], color=C_RED, linewidth=2.4,
               zorder=6,
               label=f'盈亏平衡所需 {be["breakeven_at_lowest"]:.0f}%')
    ax.fill_between([-0.6, len(wrs) - 0.4],
                    be['breakeven_at_lowest'], max(wrs) * 1.35,
                    color=C_RED, alpha=0.07, zorder=1)

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=42, ha='right', fontsize=7.5,
                       rotation_mode='anchor')
    ax.set_ylabel('中奖率 %', fontsize=9, color='#475569')
    ax.set_title('② 中奖率的结构性缺口\n策略能提升中奖率, 但离不亏差一个数量级',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.legend(fontsize=8, loc='upper left', framealpha=0.9)
    ax.set_ylim(0, be['breakeven_at_lowest'] * 1.12)
    _style_ax(ax)

    gap = be['breakeven_at_lowest'] / max(wrs) if wrs else 0
    ax.text(0.5, 0.62, f'最好策略中奖率 {max(wrs):.2f}%\n'
                        f'距盈亏平衡还差 {gap:.1f} 倍',
            transform=ax.transAxes, ha='center', fontsize=9.5,
            fontweight='bold', color=C_RED,
            bbox=dict(boxstyle='round,pad=0.5', fc='white', ec=C_RED, lw=1.2,
                      alpha=0.95))
    return be


def panel_hot(ax, game, lab):
    """右图: 热号预测力 (各切分 z 分数)"""
    from data.hot_illusion import analyze_hot_illusion
    r = analyze_hot_illusion(game)
    scan = r['scan']
    splits = scan['splits']

    labels = [f"{'-'.join(s['train'])}\n→{'-'.join(s['test'])}" for s in splits]
    zs = [s['hit_z'] for s in splits]
    x = np.arange(len(zs))

    colors = []
    for s in splits:
        if abs(s['hit_z']) >= 2:
            colors.append(C_GREEN if s['hit_z'] > 0 else C_RED)
        else:
            colors.append(C_GRAY)

    ax.bar(x, zs, color=colors, width=0.55, zorder=3)
    ax.axhspan(-2, 2, color=C_GREEN, alpha=0.10, zorder=1,
               label='与随机无显著差异区间 (|z| < 2)')
    ax.axhline(0, color=C_DARK, linewidth=1.2, zorder=4)
    ax.axhline(2, color=C_GREEN, linestyle='--', linewidth=1.0, zorder=4)
    ax.axhline(-2, color=C_GREEN, linestyle='--', linewidth=1.0, zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel('命中数 z 分数', fontsize=9, color='#475569')
    ax.set_title('③ 热号有预测力吗?\n每个年份切分的检验, 全落在无差异区间',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.legend(fontsize=8, loc='upper left', framealpha=0.9)
    ax.set_ylim(-2.45, 2.45)
    _style_ax(ax)

    c = r['continuity']
    ax.text(0.5, 0.08,
            f'相邻年 Top-10 重合 {c["overlap_mean"]} vs 随机 {c["overlap_expected"]} (z={c["overlap_z"]:+.2f})\n'
            f'相邻年排名 ρ = {c["rho_mean"]:+.3f} (z={c["rho_z"]:+.2f})',
            transform=ax.transAxes, ha='center', fontsize=8.2,
            color='#334155',
            bbox=dict(boxstyle='round,pad=0.45', fc='white', ec='#cbd5e1',
                      lw=1, alpha=0.95))
    return r


def main():
    ap = argparse.ArgumentParser(description='生成门面图')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    args = ap.parse_args()

    from data.games import get_game
    cfg = get_game(args.game)
    lab = cfg.name

    print(f'生成 {lab} 门面图 (这会跑一次完整回测, 约 20-40 秒)...')
    REPORTS.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(19, 8.6))
    fig.patch.set_facecolor('white')
    # 底部给结论条 + x 标签留空间, 顶部给标题留空间
    fig.subplots_adjust(left=0.075, right=0.985, top=0.845, bottom=0.185,
                        wspace=0.30)

    strat = panel_strategies(axes[0], args.game, lab)
    be = panel_winrate(axes[1], args.game, lab, strat)
    hot = panel_hot(axes[2], args.game, lab)

    # 顶部标题
    fig.suptitle(
        f'{lab} 选号策略实证检验  —  数据说话, 不猜',
        fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             f'基于 {len(hot["all_years"])} 年真实开奖 · '
             f'严格 walk-forward 回测 · 每一项都跟随机期望做统计检验 (z 分数)',
             ha='center', fontsize=11, color=C_GRAY)

    # 底部结论条 (动态)
    all_roi = [s['roi_ex_big'] for s in strat['strategies']]
    roi_lo, roi_hi = min(all_roi), max(all_roi)
    gap = be['breakeven_at_lowest'] / max(
        s['win_rate'] for s in strat['strategies'])
    n_big = sum(1 for s in strat['strategies'] if s['big_prizes'] > 0)
    fig.text(0.5, 0.045,
             f'结论:  ① 所有策略 ROI(剔除大奖) 都在 {roi_lo:.0f}%~{roi_hi:.0f}%, 无一转正    '
             f'② 中奖率再高也跨不过 {gap:.1f} 倍缺口    '
             f'③ 热号(含最近 3 年)与随机无差异    '
             f'→  凯利 f* = 0: 数学公式的建议是"不下注"',
             ha='center', fontsize=11, color='white', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.65', fc=C_DARK, ec='none'))
    if n_big:
        fig.text(0.985, 0.045,
                 f'注: {n_big} 个策略中了大奖 (◆), 原始 ROI 见标注',
                 ha='right', fontsize=8.5, color='#94a3b8')

    out = REPORTS / f'headline_{args.game}.png'
    fig.savefig(out, dpi=145, bbox_inches='tight',
                facecolor='white', pad_inches=0.3)
    plt.close(fig)

    size = out.stat().st_size / 1024
    print(f'✅ 已生成: {out}  ({size:.0f} KB)')
    print(f'   → README 顶部插入: ![门面图](reports/headline_{args.game}.png)')
    return out


if __name__ == '__main__':
    main()
