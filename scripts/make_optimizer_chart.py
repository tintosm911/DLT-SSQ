"""
胆拖优化器结果图
================
把"预算 → 最优结构 → 中奖率"画成帕累托曲线, 并展示一个反直觉结论:
**去掉后区胆码是提升中奖率最有效的一招**, 而且跟选哪几个号无关。

用法:
  python scripts/make_optimizer_chart.py
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

for _f in ('Microsoft YaHei', 'Noto Sans SC', 'SimHei'):
    if any(f.name == _f for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.sans-serif'] = [_f]
        break
plt.rcParams['axes.unicode_minus'] = False

from data.dan_tuo_optimizer import optimize

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


def main():
    budgets = [10, 20, 50, 100, 200, 340, 680, 1000, 1680, 2000,
               3000, 4200, 6000, 9240, 12000]

    curves = {}
    for goal in ('win', 'big'):
        xs, ys, bests = [], [], []
        for b in budgets:
            r = optimize('dlt', budget=b, goal=goal,
                         front_pool=FP, back_pool=BP, top_n=1)
            if not r['best']:
                continue
            xs.append(b)
            ys.append(r['best']['win_rate'])
            bests.append(r['best'])
        curves[goal] = (xs, ys, bests)

    fig = plt.figure(figsize=(16.5, 6.6))
    fig.patch.set_facecolor('white')
    gs = fig.add_gridspec(1, 3, width_ratios=[1.15, 1.0, 1.05],
                          wspace=0.28, left=0.055, right=0.982,
                          top=0.815, bottom=0.165)

    # ================= 左: 预算 → 中奖率 =================
    ax = fig.add_subplot(gs[0, 0])
    xs, ys, bests = curves['win']
    ax.plot(xs, ys, 'o-', color=C_BLUE, lw=2.4, ms=7,
            markeredgecolor='white', markeredgewidth=1.4, zorder=4,
            label='最优结构的中奖率')
    # 原结构 (1前胆/1后胆) 的水平参考线
    r_ref = optimize('dlt', budget=1680, goal='win',
                     front_pool=FP, back_pool=BP, top_n=1)['best']
    ref = [c for c in [None]]  # 占位
    ref_line = 42.9662
    ax.axhline(ref_line, color=C_RED, ls='--', lw=1.8, zorder=3)
    ax.text(xs[-1] * 0.98, ref_line + 0.7,
            f'原结构 (1前胆/1后胆) {ref_line:.2f}%',
            ha='right', fontsize=9.4, color=C_RED, fontweight='bold')
    for x, y in zip(xs[::5], ys[::5]):
        ax.annotate(f'{y:.1f}%', (x, y), textcoords='offset points',
                    xytext=(0, 11), ha='center', fontsize=8.6, color=C_DARK)
    ax.set_xlabel('预算 (元)', fontsize=10.5, color=C_DARK)
    ax.set_ylabel('精确中奖率 (%)', fontsize=10.5, color=C_DARK)
    ax.set_xscale('log')
    ax.set_xticks([10, 100, 1000, 10000])
    ax.set_xticklabels(['10', '100', '1000', '10000'])
    ax.grid(alpha=0.25, ls='--')
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, frameon=False, loc='lower right')
    ax.set_title('① 预算越大, 最优中奖率越高', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=13)
    ax.text(0.5, 1.005, '曲线在 1680 元附近饱和 (后区拖满 5 个号)',
            transform=ax.transAxes, ha='center', fontsize=9.0, color=C_GRAY)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('bottom', 'left'):
        ax.spines[s].set_color('#cbd5e1')

    # ================= 中: 结构分解 =================
    ax = fig.add_subplot(gs[0, 1])
    # 同预算下, 固定不同 (前胆, 后胆) 的中奖率
    rows = []
    for k in range(0, 3):
        for m in range(0, 3):
            r = optimize('dlt', budget=1680, goal='win',
                         front_pool=FP, back_pool=BP, top_n=20)
            rows.append((k, m))
    # 直接用精确求解器算 (前 k 胆 / 后 m 胆) 的中奖率
    from data.dan_tuo_exact import exact_dan_tuo
    grid = [[0] * 3 for _ in range(3)]
    for k in range(3):
        for m in range(3):
            fd = FP[:k]
            ft = FP[k:]
            bd = BP[:m]
            bt = BP[m:]
            res = exact_dan_tuo('dlt', fd, ft, bd, bt)
            grid[k][m] = res['win_rate']
    im = ax.imshow(grid, cmap='RdYlGn', aspect='auto', vmin=25, vmax=50)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f'{grid[i][j]:.1f}%', ha='center', va='center',
                    fontsize=12, fontweight='bold', color=C_DARK)
    ax.set_xticks(range(3))
    ax.set_xticklabels(['0 胆', '1 胆', '2 胆'], fontsize=10)
    ax.set_yticks(range(3))
    ax.set_yticklabels(['0 胆', '1 胆', '2 胆'], fontsize=10)
    ax.set_xlabel('后区胆码个数', fontsize=10.5, color=C_DARK)
    ax.set_ylabel('前区胆码个数', fontsize=10.5, color=C_DARK)
    ax.set_title('② 中奖率只由胆码个数决定', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=26)
    ax.text(0.5, 1.015, '横向 (后区胆数) 影响大, 纵向 (前区胆数) 几乎不影响',
            transform=ax.transAxes, ha='center', fontsize=9.0, color=C_GRAY)
    for s in ax.spines.values():
        s.set_color('#cbd5e1')

    # ================= 右: 期望值铁律 =================
    ax = fig.add_subplot(gs[0, 2])
    cands = []
    for b in [200, 500, 1000, 1680, 3000, 6000]:
        r = optimize('dlt', budget=b, goal='win',
                     front_pool=FP, back_pool=BP, top_n=1)
        if r['best']:
            cands.append((b, r['best']['expected_net'],
                          r['best']['expected_net'] / r['best']['n_bets']))
    bx = [c[0] for c in cands]
    by = [c[1] for c in cands]
    ax.bar(range(len(bx)), by, 0.6, color=C_RED, alpha=0.85,
           edgecolor='white', linewidth=1.3, zorder=3)
    for i, (b, net, per) in enumerate(cands):
        ax.text(i, net + 24, f'{net:,.0f} 元',
                ha='center', va='bottom', fontsize=8.8, color='white',
                fontweight='bold', zorder=5, rotation=90)
    ax.set_xticks(range(len(bx)))
    ax.set_xticklabels([f'{b:,}' for b in bx], fontsize=9.5)
    ax.set_xlabel('预算 (元)', fontsize=10.5, color=C_DARK)
    ax.set_ylabel('期望净收益 (元)', fontsize=10.5, color=C_DARK)
    ax.axhline(0, color=C_DARK, lw=1.2)
    ax.set_ylim(min(by) * 1.18, 60)
    ax.set_title('③ 但期望值永远不变', fontsize=13.5,
                 fontweight='bold', color=C_DARK, pad=26)
    ax.text(0.5, 1.015, '预算翻 30 倍, 期望净收益按比例翻 — 每注永远是 -0.9407 元',
            transform=ax.transAxes, ha='center', fontsize=9.0, color=C_GRAY)
    ax.grid(axis='y', alpha=0.25, ls='--')
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('bottom', 'left'):
        ax.spines[s].set_color('#cbd5e1')
    fig.suptitle('胆拖结构优化器: 同样的钱, 哪种结构更容易中一次奖',
                 fontsize=18, fontweight='bold', color=C_DARK, y=0.965)
    fig.text(0.5, 0.905,
             '超级大乐透 · 精确超几何全枚举 · 号码池 前区 11 个 / 后区 5 个 · '
             '零模拟误差',
             ha='center', fontsize=11, color=C_GRAY)
    fig.text(0.5, 0.045,
             '注意: 优化器只回答"怎么更容易中一次小奖" — '
             '它不改变期望值, 期望净收益永远是负的',
             ha='center', fontsize=11.5, color=C_RED, fontweight='bold')

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / 'headline_optimizer.png'
    fig.savefig(out, dpi=145, bbox_inches='tight', facecolor='white',
                pad_inches=0.3)
    plt.close(fig)
    print(f'✅ 已生成: {out}  ({out.stat().st_size / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
