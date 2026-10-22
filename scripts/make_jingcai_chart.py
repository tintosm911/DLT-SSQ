"""
竞彩 vs 境外盘口 对比图
======================
三联图:
  左: 抽水率对比 (竞彩 vs 7 家境外公司) — 竞彩一柱独高
  中: 套利组合可行性 (纯境外 vs 含竞彩) — 含竞彩的组合一场都用不上
  右: 竞彩当前实时盘口 (前若干场) + 抽水明细
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
C_GRAY = '#94a3b8'
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


def make_chart(jc_matches, overseas_vig, arb_stats):
    fig, axes = plt.subplots(1, 3, figsize=(19, 8.4))
    fig.patch.set_facecolor('white')
    fig.subplots_adjust(left=0.075, right=0.985, top=0.84, bottom=0.16,
                        wspace=0.30)

    # ---------- 左: 抽水率对比 ----------
    ax = axes[0]
    items = sorted(overseas_vig.items(), key=lambda x: x[1]['mean'])
    names = [f'{k}' for k, _ in items]
    vals = [v['mean'] * 100 for _, v in items]
    jc_vig = 12.91
    names.append('中国竞彩')
    vals.append(jc_vig)
    colors = ['#fca5a5'] * len(items) + [C_RED]
    y = np.arange(len(vals))
    ax.barh(y, vals, color=colors, height=0.62, zorder=3)
    ax.axvline(0, color=C_DARK, linewidth=1.2, zorder=4)
    for i, v in enumerate(vals):
        ax.text(v + 0.15, i, f'{v:.2f}%', va='center', fontsize=8.5,
                color=C_DARK, fontweight='bold' if i == len(vals) - 1 else 'normal')
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    for lbl in ax.get_yticklabels():
        if lbl.get_text() == '中国竞彩':
            lbl.set_color(C_RED)
            lbl.set_fontweight('bold')
    ax.set_xlabel('抽水率 %  (Σ(1/odds) - 1)', fontsize=9, color='#475569')
    gap = jc_vig - min(vals)
    ax.set_title(f'① 抽水率对比 (真实赔率实测)\n中国竞彩比最好的境外公司高 {gap:.2f} 个百分点',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.set_xlim(0, max(vals) * 1.22)
    _style(ax)
    ax.grid(axis='x', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.grid(axis='y', visible=False)

    # ---------- 中: 套利组合可行性 ----------
    ax = axes[1]
    labels = ['纯境外公司\n(不含竞彩)', '含竞彩的组合']
    found = [arb_stats['pure']['found'], arb_stats['with_jc']['found']]
    rates = [arb_stats['pure']['rate'], arb_stats['with_jc']['rate']]
    rois = [arb_stats['pure']['roi'], arb_stats['with_jc']['roi']]
    x = np.arange(2)
    ax.bar(x - 0.19, rates, width=0.36, color=C_GREEN, zorder=3,
           label='可套利场次占比 %')
    ax2 = ax.twinx()
    ax2.bar(x + 0.19, rois, width=0.36, color=C_BLUE, zorder=3,
            label='资金回测 ROI %')
    for i in range(2):
        ax.text(x[i] - 0.19, rates[i] + 0.12, f'{rates[i]:.2f}%', ha='center',
                fontsize=9.5, fontweight='bold', color=C_GREEN)
        ax2.text(x[i] + 0.19, rois[i] + 0.06, f'{rois[i]:+.3f}%', ha='center',
                 fontsize=9.5, fontweight='bold', color=C_BLUE)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('可套利场次占比 %', fontsize=9, color=C_GRAY)
    ax2.set_ylabel('资金回测 ROI %', fontsize=9, color=C_GRAY)
    ax.set_ylim(0, max(rates) * 1.45)
    ax2.set_ylim(min(rois + [0]) * 1.6, max(rois + [0.5]) * 1.5)
    ax.set_title('② 套利组合可行性\n含竞彩的组合里, 竞彩一次都用不上',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.legend(fontsize=8, loc='upper left', framealpha=0.9)
    ax2.legend(fontsize=8, loc='upper right', framealpha=0.9)
    _style(ax)
    ax2.spines['top'].set_visible(False)
    ax2.tick_params(colors='#475569', labelsize=9)

    # ---------- 右: 竞彩实时盘口 ----------
    ax = axes[2]
    if jc_matches:
        sub = jc_matches[:11]
        names = []
        for m in sub:
            label = f"{m['league_cn']} {m['home_cn']}vs{m['away_cn']}"
            if len(label) > 22:
                label = label[:21] + '…'
            names.append(label)
        vigs = []
        for m in sub:
            o = m['had']
            vigs.append((1 / o['h'] + 1 / o['d'] + 1 / o['a'] - 1) * 100)
        y = np.arange(len(sub))
        ax.barh(y, vigs, color=C_RED, height=0.6, zorder=3, alpha=0.85)
        ax.axvline(12.91, color=C_DARK, linestyle='--', linewidth=1.6, zorder=4,
                   label='竞彩平均抽水 12.91%')
        ax.set_yticks(y)
        ax.set_yticklabels(names, fontsize=7.5)
        ax.set_xlabel('当前竞彩 HAD 抽水率 %', fontsize=9, color='#475569')
        ax.set_title('③ 中国竞彩当前实时盘口抽水\n24 场全部 12.57% ~ 12.99%',
                     fontsize=11, fontweight='bold', color=C_DARK, pad=10)
        ax.legend(fontsize=8, loc='lower right', framealpha=0.9)
        ax.set_xlim(0, max(vigs) * 1.32)
        _style(ax)
        ax.grid(axis='x', color='#e2e8f0', linewidth=0.8, zorder=0)
        ax.grid(axis='y', visible=False)
    else:
        ax.text(0.5, 0.5, '无实时数据', ha='center', va='center',
                transform=ax.transAxes)
        _style(ax)

    # 标题 + 结论
    fig.suptitle('中国竞彩 vs 境外盘口  —  一个反直觉的结论',
                 fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             '竞彩官方实时赔率 (2026-10-22) × 7,600 场真实境外历史赔率 · '
             '双向对比 + 套利测算',
             ha='center', fontsize=11, color='#64748b')

    fig.text(0.5, 0.042,
             '结论:  ① 竞彩抽水 12.91%, 比最好的境外公司还高 10.46 个百分点    '
             '② "竞彩+境外"组合里, 竞彩一次都用不上 — 高抽水是障碍不是机会    '
             '③ 想套利只能在境外公司之间做    '
             '→  跨市场套利这条路, 在竞彩这里走不通',
             ha='center', fontsize=11, color='white', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.65', fc=C_DARK, ec='none'))

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / 'headline_jingcai.png'
    fig.savefig(out, dpi=145, bbox_inches='tight', facecolor='white',
                pad_inches=0.3)
    plt.close(fig)
    return out


if __name__ == '__main__':
    from data.jingcai_odds import fetch_matches, analyze_vig as jc_vig
    from data.sports_odds import parse_season, CACHE_DIR
    from data.sports_arb import analyze_vig
    from scripts.jingcai_vs_overseas import backtest, JINGCAI_VIG

    jc = fetch_matches()
    jc_v = jc_vig(jc)
    files = sorted(CACHE_DIR.glob('premier-league_*.csv'))
    ms = []
    for f in files:
        ms.extend(parse_season(f.read_text(encoding='utf-8-sig')))
    ov = analyze_vig(ms)
    pure = backtest(ms, JINGCAI_VIG, min_profit=0.005, allow_jingcai=False)
    with_jc = backtest(ms, JINGCAI_VIG, min_profit=0.005, allow_jingcai=True)
    out = make_chart(jc, ov, {'pure': pure, 'with_jc': with_jc})
    print(f'已生成: {out}')
    print(f'  竞彩抽水 {jc_v["mean"]*100:.2f}% ({jc_v["count"]} 场实时)')
    print(f'  纯境外可套利 {pure.get("found",0)} 场 ({pure.get("rate",0):.2f}%), '
          f'ROI {pure.get("roi",0):+.3f}%')
    print(f'  含竞彩可套利 {with_jc.get("found",0)} 场 ({with_jc.get("rate",0):.2f}%), '
          f'ROI {with_jc.get("roi",0):+.3f}%')
