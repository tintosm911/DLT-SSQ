"""
胆拖结构分析图
==============
把"胆拖结构"这件事画成三联图:

  左: 结构矩阵热力图 —— 中奖率只取决于胆码**个数**
      (前区胆数 × 后区胆数), 旁边的注数标注每个格子的组合规模
  中: 同预算方案对比 —— 中奖率 vs ≥1万大奖概率的权衡
  右: 冷热排名 vs 概率 —— 逐号冷热排名对中奖概率的影响 = 0

★ 核心信息: 冷热对概率零影响, 只有"胆码个数"影响中奖率,
  而期望值对所有结构都一样。

用法:
  python scripts/make_dantuo_chart.py
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

from data.dan_tuo_exact import exact_dan_tuo
from data.games import get_game

REPORTS = PROJECT_ROOT / 'reports'

C_DARK = '#0f172a'
C_GRAY = '#64748b'
C_LIGHT = '#f1f5f9'
C_RED = '#dc2626'
C_BLUE = '#2563eb'
C_GREEN = '#059669'
C_AMBER = '#d97706'

FP = [2, 4, 6, 10, 14, 16, 18, 23, 26, 32, 35]
BP = [2, 4, 6, 9, 12]


def matrix():
    """前胆数 × 后胆数 → 中奖率"""
    grid = np.full((6, 3), np.nan)
    notes = {}
    for k in range(6):
        for m in range(3):
            r = exact_dan_tuo('dlt', FP[:k], FP[k:], BP[:m], BP[m:])
            grid[k, m] = r['win_rate']
            notes[(k, m)] = (r['n_bets'], r['cost'])
    return grid, notes


def main():
    cfg = get_game('dlt')
    grid, notes = matrix()

    fig = plt.figure(figsize=(17, 6.4))
    fig.patch.set_facecolor('white')
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.15, 1.25],
                          wspace=0.30, left=0.055, right=0.982,
                          top=0.845, bottom=0.155)

    # ================= 左: 结构矩阵 =================
    ax = fig.add_subplot(gs[0, 0])
    im = ax.imshow(grid, cmap='RdYlGn', aspect='auto', vmin=14, vmax=50)
    ax.set_xticks(range(3))
    ax.set_xticklabels(['后区 0 胆', '后区 1 胆', '后区 2 胆'], fontsize=9.5)
    ax.set_yticks(range(6))
    ax.set_yticklabels([f'前区 {k} 胆' for k in range(6)], fontsize=9.5)
    ax.set_xlabel('后区胆码数量', fontsize=10.5, color=C_DARK)
    ax.set_ylabel('前区胆码数量', fontsize=10.5, color=C_DARK)
    for i in range(6):
        for j in range(3):
            v = grid[i, j]
            n, c = notes[(i, j)]
            # 按色深自动选字色, 保证深色格也看得清
            r_, g_, b_, _ = im.cmap(im.norm(v))
            lum = 0.299 * r_ + 0.587 * g_ + 0.114 * b_
            fg = '#ffffff' if lum < 0.62 else C_DARK
            ax.text(j, i - 0.16, f'{v:.1f}%', ha='center', va='center',
                    fontsize=11.5, fontweight='bold', color=fg)
            ax.text(j, i + 0.22, f'{n:,} 注 / {c:,.0f} 元', ha='center', va='center',
                    fontsize=7.8, color=fg, alpha=0.92)
    ax.set_title('① 中奖率只取决于「胆码个数」', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=13)
    ax.text(0.5, -0.215, '同一行(后区胆数相同) → 中奖率完全相同, 号码冷热零影响',
            transform=ax.transAxes, ha='center', fontsize=9.2, color=C_GRAY)
    for s in ax.spines.values():
        s.set_color('#cbd5e1')

    # ================= 中: 同预算方案对比 =================
    ax = fig.add_subplot(gs[0, 1])
    schemes = [
        ('A 原方案\n1前胆/1后胆', [6], [x for x in FP if x != 6], [4], [x for x in BP if x != 4]),
        ('B 去后区胆\n2前胆/0后胆', [2, 4], [x for x in FP if x not in (2, 4)], [], list(BP)),
        ('C 追热号\n2前胆/1后胆', [32, 35], [x for x in FP if x not in (32, 35)], [12], [x for x in BP if x != 12]),
        ('D 双区零胆\n0前胆/0后胆', [], list(FP), [], list(BP)),
    ]
    labels, wins, bigs, costs = [], [], [], []
    for lab, fd, ft, bd, bt in schemes:
        r = exact_dan_tuo('dlt', fd, ft, bd, bt)
        p1w = sum(p['prob_any'] for p in r['prize_dist'] if p['money'] >= 10000) * 100
        labels.append(lab)
        wins.append(r['win_rate'])
        bigs.append(p1w)
        costs.append(r['cost'])

    x = np.arange(len(labels))
    w = 0.36
    b1 = ax.bar(x - w / 2, wins, w, label='中奖率 (任意奖级)',
                color=C_BLUE, edgecolor='white', linewidth=1.2)
    b2 = ax.bar(x + w / 2, bigs, w, label='≥1万 大奖概率',
                color=C_RED, edgecolor='white', linewidth=1.2)
    for b in list(b1) + list(b2):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.6,
                f'{b.get_height():.2f}%' if b.get_height() > 5
                else f'{b.get_height():.3f}%',
                ha='center', fontsize=8.4, color=C_DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.6)
    ax.set_ylabel('概率 (%)', fontsize=10.5, color=C_DARK)
    ax.set_ylim(0, 56)
    ax.legend(fontsize=9, frameon=False, loc='upper left')
    ax.grid(axis='y', alpha=0.25, ls='--')
    ax.set_axisbelow(True)
    ax.set_title('② 中奖率 vs 大奖概率 (结构决定, 与号码无关)', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=13)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('bottom', 'left'):
        ax.spines[s].set_color('#cbd5e1')
    ax.text(0.5, -0.215, 'D 中大奖概率是 A 的 2.6 倍, 但要 5.5 倍的钱',
            transform=ax.transAxes, ha='center', fontsize=9.2, color=C_GRAY)

    # ================= 右: 冷热档 vs 实际出现频率 (实证检验) =================
    ax = fig.add_subplot(gs[0, 2])
    from scripts.analyze_dantuo import load_stats, rank_table
    st = load_stats('dlt')
    f_rank = rank_table(st['front'])

    # 把前区 35 个号按冷热排名分成 7 档 (每档 5 个)
    n_draw = st['n']
    theory = n_draw * cfg.front_count / cfg.front_range
    counts = st['front']['count']
    by_rank = {v: int(counts[v - 1]) for v in range(1, cfg.front_range + 1)}
    bins = []
    for b in range(7):
        ranks = list(range(b * 5 + 1, b * 5 + 6))
        vals = [by_rank[r] for r in ranks]
        bins.append((b, ranks, sum(vals) / len(vals)))

    xs = [b[0] for b in bins]
    ys = [b[2] for b in bins]
    # 每档 5 个号 × 每期 5 个号 → 理论期望出现次数
    err = [np.std([by_rank[r] for r in b[1]], ddof=1) / np.sqrt(5) for b in bins]

    colors = [C_RED if b[0] == 0 else (C_BLUE if b[0] == 6 else C_GRAY) for b in bins]
    ax.bar(xs, ys, 0.62, color=colors, alpha=0.9, edgecolor='white',
           linewidth=1.4, zorder=3,
           yerr=err, capsize=4, error_kw=dict(ecolor='#475569', lw=1.2))
    ax.axhline(theory, color=C_AMBER, lw=2.2, ls='--', zorder=4)
    for b, y in zip(bins, ys):
        ax.text(b[0], y + 6.5, f'{y:.0f}', ha='center', fontsize=8.6,
                color=C_DARK, fontweight='bold', zorder=5)
    ax.set_xticks(xs)
    ax.set_xticklabels([f'最热\n{b[1][0]}-{b[1][-1]}' if b[0] == 0
                         else (f'最冷\n{b[1][0]}-{b[1][-1]}' if b[0] == 6
                               else f'{b[1][0]}-{b[1][-1]}') for b in bins],
                       fontsize=8.4)
    ax.set_ylim(0, 520)
    ax.set_xlabel('按冷热排名分档 (前区 35 个号, 每档 5 个)', fontsize=10.5, color=C_DARK)
    ax.set_ylabel('每号平均出现次数', fontsize=10.5, color=C_DARK)
    ax.set_title('③ 实证检验: 热号并没有更多出', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=13)
    ax.text(0.5, -0.215,
            f'{n_draw} 期真实数据 · 各档出现次数都贴着理论值, 误差棒内无单调趋势',
            transform=ax.transAxes, ha='center', fontsize=9.2, color=C_GRAY)
    ax.grid(axis='y', alpha=0.25, ls='--')
    ax.set_axisbelow(True)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker='s', ls='', color=C_RED, label='最热 5 个号'),
                       Line2D([], [], marker='s', ls='', color=C_BLUE, label='最冷 5 个号'),
                       Line2D([], [], ls='--', color=C_AMBER,
                              label=f'均匀理论值 {theory:.1f}')],
              fontsize=8.8, frameon=False, loc='upper center', ncol=3,
              bbox_to_anchor=(0.5, 1.0))
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('bottom', 'left'):
        ax.spines[s].set_color('#cbd5e1')

    # ================= 标题 + 结论条 =================
    fig.suptitle('胆拖结构分析: 只有「胆码个数」影响中奖率, 冷热一律无效',
                 fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             '超级大乐透 · 精确超几何全枚举 (零抽样误差) · 号码池 前区 11 个 / 后区 5 个 · '
             '大乐透 2938 期真实数据',
             ha='center', fontsize=11, color=C_GRAY)
    fig.text(0.5, 0.045,
             '注意: 所有结构的单注期望净收益都是 -0.9407 元 — 换任何胆拖方案都改不了期望值, '
             '只能改变「花多少」和「多容易中一次小奖」',
             ha='center', fontsize=11.5, color=C_RED, fontweight='bold')

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / 'headline_dantuo.png'
    fig.savefig(out, dpi=145, bbox_inches='tight', facecolor='white',
                pad_inches=0.3)
    plt.close(fig)
    print(f'✅ 已生成: {out}  ({out.stat().st_size / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
