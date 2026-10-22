"""
生成桌面端图标
================
画一个简洁的"热力球"图标 (深色底 + 红蓝号码球), 输出 PNG + ICO.

用法:
  python scripts/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np

OUT_DIR = PROJECT_ROOT / 'desktop' / 'src-tauri' / 'icons'


def draw_icon(size: int = 1024):
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # 圆角深色底
    ax.add_patch(Circle((50, 50), 48, color='#0f172a', zorder=1))
    ax.add_patch(Circle((50, 50), 44, color='#1e293b', zorder=2))

    # 三个号码球: 红(热) 蓝(冷) 金(中性)
    balls = [
        (32, 62, 20, '#dc2626', '7'),
        (66, 66, 16, '#2563eb', '3'),
        (50, 32, 22, '#f59e0b', '9'),
    ]
    for x, y, r, color, label in balls:
        # 球体渐变感: 深色外圈 + 主体 + 高光
        ax.add_patch(Circle((x, y), r + 2.5, color='#0b1220', zorder=3))
        ax.add_patch(Circle((x, y), r, color=color, zorder=4))
        ax.add_patch(Circle((x - r * 0.32, y + r * 0.32), r * 0.26,
                            color='white', alpha=0.34, zorder=5))
        ax.text(x, y - r * 0.04, label, ha='center', va='center',
                fontsize=r * 1.25, color='white', fontweight='bold',
                zorder=6)

    # 热力波纹 (表达"冷热度分析")
    for i, rad in enumerate([26, 33, 40]):
        ax.add_patch(Circle((50, 50), rad, fill=False, color='#f59e0b',
                            alpha=0.16 - i * 0.04, linewidth=2.5, zorder=2))

    return fig


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 主 PNG (1024)
    fig = draw_icon(1024)
    png = OUT_DIR / 'icon.png'
    fig.savefig(png, dpi=100, facecolor='none', transparent=False)
    plt.close(fig)
    print(f'  ✅ {png.name}  {png.stat().st_size/1024:.1f} KB')

    # 多种尺寸 PNG
    for s, name in ((32, '32x32.png'), (128, '128x128.png'),
                    (256, '128x128@2x.png'), (64, '64x64.png')):
        fig = draw_icon(s)
        p = OUT_DIR / name
        fig.savefig(p, dpi=100, facecolor='#0f172a')
        plt.close(fig)
        print(f'  ✅ {name}  {p.stat().st_size/1024:.1f} KB')

    # ICO (多尺寸打包)
    try:
        from PIL import Image
        ico = OUT_DIR / 'icon.ico'
        img = Image.open(png)
        img.save(ico, format='ICO',
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128),
                        (256, 256)])
        print(f'  ✅ icon.ico  {ico.stat().st_size/1024:.1f} KB')
    except ImportError:
        # 没 PIL 就用 PNG 转 (Tauri 只需要 ico 存在, 打包时会转)
        import shutil
        shutil.copy(png, OUT_DIR / 'icon.ico')
        print('  ⚠️ 无 Pillow, icon.ico 暂用 PNG (打包时会自动转)')

    print(f'\n  输出目录: {OUT_DIR}')


if __name__ == '__main__':
    main()
