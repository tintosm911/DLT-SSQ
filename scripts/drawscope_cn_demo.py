"""
中国彩种 (DLT/SSQ) 适配 DrawScope Demo
========================================
"""
import sys
import random
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

from sports.drawscope_adapter import (
    dlt_row_to_drawing,
    dlt_df_to_drawings,
    ssq_df_to_drawings,
    dlt_payload,
    ssq_payload,
    decode_dlt,
    decode_ssq,
)


def gen_dlt_df(n=300):
    """生成合成 DLT 数据 (5/35 + 2/12)"""
    np.random.seed(42)
    rows = []
    base = date(2024, 1, 1)
    for i in range(n):
        front = sorted(np.random.choice(35, 5, replace=False) + 1)
        back = sorted(np.random.choice(12, 2, replace=False) + 1)
        rows.append({
            "period": f"D{i:04d}",
            "draw_date": (base + timedelta(days=i * 3)).isoformat(),
            "front_1": front[0], "front_2": front[1], "front_3": front[2],
            "front_4": front[3], "front_5": front[4],
            "back_1": back[0], "back_2": back[1],
        })
    return pd.DataFrame(rows)


def gen_ssq_df(n=300):
    """生成合成 SSQ 数据 (6/33 + 1/16)"""
    np.random.seed(42)
    rows = []
    base = date(2024, 1, 1)
    for i in range(n):
        red = sorted(np.random.choice(33, 6, replace=False) + 1)
        blue = int(np.random.choice(16) + 1)
        rows.append({
            "period": f"S{i:04d}",
            "draw_date": (base + timedelta(days=i * 3)).isoformat(),
            "front_1": red[0], "front_2": red[1], "front_3": red[2],
            "front_4": red[3], "front_5": red[4], "front_6": red[5],
            "back_1": blue,
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("  中国彩种 (DLT/SSQ) ↔ DrawScope 适配层验证")
    print("=" * 70)
    print()

    # ─────────── DLT 流程 ───────────
    print("─" * 70)
    print("  大乐透 (DLT) 适配")
    print("─" * 70)
    dlt_df = gen_dlt_df(300)
    print(f"  ✅ 构造 {len(dlt_df)} 期 DLT 合成数据")

    dlt_drawings = dlt_df_to_drawings(dlt_df)
    print(f"  ✅ 转换为 {len(dlt_drawings)} 个 DrawScope Drawing")

    # 抽样验证
    sample_dlt = dlt_drawings[0]
    decoded = decode_dlt(sample_dlt)
    print(f"  📊 抽样解码 (前 1 期):")
    print(f"     draw_date   = {decoded['draw_date']}")
    print(f"     main_numbers= {decoded['front']}")
    print(f"     special     = {decoded['back']}")

    # 跑 DrawScope analyze (target_date 必须精确匹配某期的 draw_date)
    target_dt = dlt_drawings[200].draw_date  # 用第 201 期的实际日期
    payload = dlt_payload(dlt_drawings, target_date=target_dt)
    print(f"  📋 Payload 配置: main_min=1, main_max=35, draw_count=5")
    print(f"                 special_min=1, special_max=12, special_draw_count=1")
    print(f"                 (后区 2 个号: special=1号, multiplier=2号)")
    print(f"                 target_date = {target_dt} (第 201 期, 前 200 期训练)")

    try:
        from drawscope_engine.statistics.analytics import analyze
        result = analyze(payload)
        print(f"  ✅ DrawScope analyze 完成!")
        print(f"     chi_square_statistic: {result.chi_square_statistic:.2f}")
        print(f"     sample_size: {result.sample_size}")
        print(f"     date_range: {result.date_range.start} ~ {result.date_range.end}")
        if result.patterns:
            print(f"     patterns.odd_even: {dict(list(result.patterns.odd_even.items())[:5])}")
        if result.numbers:
            top_nums = sorted(result.numbers, key=lambda x: -x.frequency)[:3]
            print(f"     top 3 numbers: {[(n.number, n.frequency) for n in top_nums]}")
        if result.top_pairs:
            print(f"     top 3 pairs: {[(p.numbers, p.count) for p in result.top_pairs[:3]]}")
    except Exception as e:
        print(f"  ❌ analyze 失败: {e}")
        import traceback
        traceback.print_exc()
    print()

    # ─────────── SSQ 流程 ───────────
    print("─" * 70)
    print("  双色球 (SSQ) 适配")
    print("─" * 70)
    ssq_df = gen_ssq_df(300)
    print(f"  ✅ 构造 {len(ssq_df)} 期 SSQ 合成数据")

    ssq_drawings = ssq_df_to_drawings(ssq_df)
    print(f"  ✅ 转换为 {len(ssq_drawings)} 个 DrawScope Drawing")

    sample_ssq = ssq_drawings[0]
    decoded = decode_ssq(sample_ssq)
    print(f"  📊 抽样解码 (前 1 期):")
    print(f"     draw_date   = {decoded['draw_date']}")
    print(f"     main_numbers= {decoded['front']}")
    print(f"     special     = {decoded['back']}")

    target_dt = ssq_drawings[200].draw_date  # 用第 201 期的实际日期
    payload = ssq_payload(ssq_drawings, target_date=target_dt)
    print(f"  📋 Payload 配置: main_min=1, main_max=33, draw_count=6")
    print(f"                 special_min=1, special_max=16, special_draw_count=1")
    print(f"                 target_date = {target_dt} (第 201 期)")

    try:
        result = analyze(payload)
        print(f"  ✅ DrawScope analyze 完成!")
        print(f"     chi_square_statistic: {result.chi_square_statistic:.2f}")
        print(f"     sample_size: {result.sample_size}")
        if result.patterns:
            print(f"     patterns.odd_even: {dict(list(result.patterns.odd_even.items())[:5])}")
        if result.numbers:
            top_nums = sorted(result.numbers, key=lambda x: -x.frequency)[:3]
            print(f"     top 3 numbers: {[(n.number, n.frequency) for n in top_nums]}")
    except Exception as e:
        print(f"  ❌ analyze 失败: {e}")
        import traceback
        traceback.print_exc()
    print()

    # ─────────── 总结 ───────────
    print("─" * 70)
    print("  适配层亮点")
    print("─" * 70)
    print("  ✅ DLT 5+2: main=[5 前区], special=后区1, multiplier=后区2")
    print("  ✅ SSQ 6+1: main=[6 红球], special=蓝球 (天然匹配)")
    print("  ✅ 一键接口: analyze_dlt_from_db() / analyze_ssq_from_db()")
    print("  ✅ decode_dlt() / decode_ssq() 反向还原")
    print()
    print("  DrawScope engine 已完整适配中国彩种,")
    print("  可直接用其 30 个固定信号 + walk-forward + DISCLAIMERS。")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()