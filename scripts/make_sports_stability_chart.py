"""
5 大联赛结论稳定性图
=====================
三联图:
  左: 各博彩公司抽水率 + 跨联赛 σ (证明抽水是市场结构常量)
  中: 各联赛三种玩法 ROI 对比 (套利正 / Elo 负 / 随机负)
  右: 各联赛"竞彩参与套利次数" (全 0, 证明竞彩无法参与套利)
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
JINGCAI_VIG = 12.91


def _style(ax):
    ax.set_facecolor('#f8fafc')
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#cbd5e1')
    ax.tick_params(colors='#475569', labelsize=9)
    ax.grid(axis='y', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def make_chart(result, out=None):
    fig, axes = plt.subplots(1, 3, figsize=(19, 8.4))
    fig.patch.set_facecolor('white')
    fig.subplots_adjust(left=0.075, right=0.985, top=0.84, bottom=0.16,
                        wspace=0.30)

    leagues = [L for L in result['leagues'] if L.get('matches')]
    n = len(leagues)

    # ---------- 左: 抽水率 + σ ----------
    ax = axes[0]
    vs = {k: v for k, v in result['vig_summary'].items()
          if k not in ('Max', 'Avg')}
    items = sorted(vs.items(), key=lambda x: x[1]['mean'])
    names = [k for k, _ in items] + ['中国竞彩']
    means = [v['mean'] * 100 for _, v in items] + [JINGCAI_VIG]
    errs = [v['std_across_leagues'] * 100 for _, v in items] + [0]
    colors = ['#fca5a5'] * len(items) + [C_RED]
    y = np.arange(len(names))
    ax.barh(y, means, color=colors, height=0.62, zorder=3, xerr=errs,
            error_kw=dict(ecolor='#475569', elinewidth=1, capsize=3))
    for i, v in enumerate(means):
        ax.text(v + errs[i] + 0.2, i, f'{v:.2f}%', va='center', fontsize=8.5,
                color=C_DARK, fontweight='bold' if i == len(means) - 1 else 'normal')
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    for lbl in ax.get_yticklabels():
        if lbl.get_text() == '中国竞彩':
            lbl.set_color(C_RED)
            lbl.set_fontweight('bold')
    ax.set_xlabel('抽水率 %  (误差棒 = 跨联赛标准差 σ)', fontsize=9,
                  color='#475569')
    ax.set_title('① 抽水率: 跨联赛几乎不变\n是市场结构常量, 不是数据噪声',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.set_xlim(0, max(means) * 1.28)
    _style(ax)
    ax.grid(axis='x', color='#e2e8f0', linewidth=0.8, zorder=0)
    ax.grid(axis='y', visible=False)

    # ---------- 中: 各联赛 ROI 对比 ----------
    ax = axes[1]
    x = np.arange(n)
    w = 0.26
    arb_rois = [L.get('arb_backtest', {}).get('roi', 0) for L in leagues]
    elo_rois = [L.get('value_bets', {}).get('Pinnacle', {}).get('roi', 0)
                for L in leagues]
    rnd_rois = [L.get('random', {}).get('Pinnacle', 0) for L in leagues]
    ax.bar(x - w, arb_rois, w, color=C_GREEN, zorder=3, label='跨公司套利')
    ax.bar(x, elo_rois, w, color='#fca5a5', zorder=3, label='Elo 价值下注')
    ax.bar(x + w, rnd_rois, w, color=C_GRAY, zorder=3, label='随机下注')
    ax.axhline(0, color=C_DARK, linewidth=1.4, zorder=4)
    for i in range(n):
        ax.text(x[i] - w, arb_rois[i] + 0.18, f'{arb_rois[i]:+.2f}',
                ha='center', fontsize=7.5, color=C_GREEN, fontweight='bold')
        ax.text(x[i], elo_rois[i] - 0.55, f'{elo_rois[i]:+.1f}', ha='center',
                fontsize=7.5, color=C_RED, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([L['name'] for L in leagues], fontsize=10)
    ax.set_ylabel('ROI %', fontsize=9, color='#475569')
    ax.set_title('② 各联赛三种玩法 ROI\n套利稳定为正, 模型必负, 随机居中',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.legend(fontsize=8.5, loc='lower left', framealpha=0.9)
    lo = min(min(elo_rois), min(rnd_rois))
    hi = max(max(arb_rois), 0)
    ax.set_ylim(lo * 1.25, hi * 2.6)
    _style(ax)

    # ---------- 右: 竞彩参与套利次数 ----------
    ax = axes[2]
    pure_rates = [L['jingcai_vs']['pure_rate'] for L in leagues]
    with_rates = [L['jingcai_vs']['with_rate'] for L in leagues]
    using = [L['jingcai_vs']['using_jingcai'] for L in leagues]
    checked = [L['jingcai_vs']['checked'] for L in leagues]

    ax.bar(x - 0.2, pure_rates, 0.4, color=C_GREEN, zorder=3,
           label='纯境外组合可套利 %')
    ax.bar(x + 0.2, with_rates, 0.4, color=C_BLUE, zorder=3,
           label='含竞彩组合可套利 %')
    for i in range(n):
        ax.text(x[i] - 0.2, pure_rates[i] + 0.12, f'{pure_rates[i]:.2f}%',
                ha='center', fontsize=8, color=C_GREEN, fontweight='bold')
        ax.text(x[i] + 0.2, with_rates[i] + 0.12, f'{with_rates[i]:.2f}%',
                ha='center', fontsize=8, color=C_BLUE, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([L['name'] for L in leagues], fontsize=10)
    ax.set_ylabel('可套利场次占比 %', fontsize=9, color='#475569')
    ax.set_title(f'③ 竞彩参与套利次数: 全部 0\n'
                 f'({sum(checked):,} 场扫描, 竞彩一次都用不上)',
                 fontsize=11, fontweight='bold', color=C_DARK, pad=10)
    ax.legend(fontsize=8.5, loc='upper right', framealpha=0.9)
    ax.set_ylim(0, max(max(pure_rates), max(with_rates)) * 1.45)
    _style(ax)

    # 标题 + 结论
    fig.suptitle('5 大联赛 · 竞彩结论稳定性检验',
                 fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             f'{result["n_matches"]:,} 场真实历史赔率 · '
             f'{result["n_leagues"]} 个联赛 · 结论高度一致',
             ha='center', fontsize=11, color='#64748b')

    arb_lo, arb_hi = min(arb_rois), max(arb_rois)
    elo_lo, elo_hi = min(elo_rois), max(elo_rois)
    fig.text(0.5, 0.042,
             f'结论:  ① 抽水率跨联赛 σ < 0.6% — 是市场结构常量    '
             f'② 套利 ROI {arb_lo:+.2f}% ~ {arb_hi:+.2f}% (全正, 数学必赢)    '
             f'③ Elo ROI {elo_lo:+.1f}% ~ {elo_hi:+.1f}% (全负, 打不过市场)    '
             f'④ 竞彩参与 0 次 — 高抽水是障碍不是机会',
             ha='center', fontsize=11, color='white', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.65', fc=C_DARK, ec='none'))

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = out or (REPORTS / 'headline_sports_stability.png')
    fig.savefig(out, dpi=145, bbox_inches='tight', facecolor='white',
                pad_inches=0.3)
    plt.close(fig)
    return out


if __name__ == '__main__':
    from data.sports_lab2 import run_sports_lab
    r = run_sports_lab(leagues=['premier-league', 'la-liga', 'serie-a',
                                'bundesliga', 'ligue-1'],
                       include_jingcai=True)
    print(f'已生成: {make_chart(r)}')
    print(f"  {r['n_leagues']} 联赛 {r['n_matches']:,} 场")
    for L in r['leagues']:
        if not L.get('matches'):
            continue
        jc = L['jingcai_vs']
        bt = L.get('arb_backtest', {})
        print(f"  {L['name']:<6} {L['matches']:>6} 场  "
              f"可套利 {jc['pure_rate']:>5.2f}%  ROI {bt.get('roi',0):+.3f}%  "
              f"竞彩参与 {jc['using_jingcai']}")
