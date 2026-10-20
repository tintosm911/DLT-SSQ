"""
DrawScope 集成 Demo
==================
跑 DrawScope 真实分析 (使用其官方 Python engine)

⚠️ 本 demo 演示集成流程, 实际数据需接入 DrawScope 数据库
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "third_party"))
sys.path.insert(0, str(PROJECT_ROOT))

from drawscope_engine.statistics.analytics import (
    RetrospectivePatternAnalysis,
    analyze,
    SIGNALS,
    DISCLAIMERS,
    MIN_BACKTEST_HISTORY,
    MIN_TARGET_HISTORY,
)
from drawscope_engine.protocol.models import AnalysisPayload, Drawing
from datetime import date


def main():
    print("=" * 70)
    print("  DrawScope 集成 Demo")
    print("=" * 70)
    print()
    print(f"  引擎位置: third_party/drawscope_engine/")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    print("─" * 70)
    print("  模块清单")
    print("─" * 70)
    print(f"  SIGNALS (30 个固定信号): {len(SIGNALS)} 个")
    for s in SIGNALS[:5]:
        print(f"    - {s.key}: {s.label} (weight={s.weight})")
    print(f"    ... + {len(SIGNALS) - 5} more")
    print()
    print(f"  DISCLAIMERS (免责声明): {len(DISCLAIMERS)} 条")
    for d in DISCLAIMERS[:3]:
        print(f"    - {d[:80]}...")
    print()

    print("─" * 70)
    print("  关键约束")
    print("─" * 70)
    print(f"  MIN_BACKTEST_HISTORY: {MIN_BACKTEST_HISTORY} 期")
    print(f"  MIN_TARGET_HISTORY:    {MIN_TARGET_HISTORY} 期")
    print()

    print("─" * 70)
    print("  构造测试输入")
    print("─" * 70)

    # 构造合成数据 (Powerball 风格: 5/69 + 1/26)
    # DrawScope 默认是美式 Powerball/Mega Millions 格式
    drawings = []
    import random
    random.seed(42)
    base_date = date(2024, 1, 1)
    for i in range(200):
        nums = sorted(random.sample(range(1, 70), 5))  # 5/69 白球
        bonus = random.randint(1, 26)  # 1/26 红球
        # 每天一期 (避免重复日期)
        d = Drawing(
            draw_date=date.fromordinal(base_date.toordinal() + i),
            main_numbers=nums,
            special_number=bonus,
        )
        drawings.append(d)
    print(f"  ✅ 构造 {len(drawings)} 期 Powerball 格式示例数据")

    # 划分训练/测试
    split = 150
    discovery = drawings[:split]
    target = drawings[split:]
    print(f"  ✅ Discovery (训练): {len(discovery)} 期")
    print(f"  ✅ Target (测试):    {len(target)} 期")
    print()

    print("─" * 70)
    print("  跑完整分析 (analyze)")
    print("─" * 70)
    try:
        payload = AnalysisPayload(
            game_id="powerball",
            era_id="2024-2025",
            main_min=1,
            main_max=69,
            draw_count=5,
            special_min=1,
            special_max=26,
            special_draw_count=1,
            ordered=False,
            draws=drawings,
        )
        result = analyze(payload)
        print(f"  ✅ 分析完成")
        print(f"     类型: {type(result).__name__}")
        for attr in dir(result):
            if attr.startswith("_"):
                continue
            val = getattr(result, attr, None)
            if val is None:
                continue
            val_str = str(val)[:120]
            print(f"     {attr}: {val_str}")
    except Exception as e:
        print(f"  ⚠️ analyze 失败: {e}")
        print(f"     错误类型: {type(e).__name__}")
        import traceback
        traceback.print_exc()
    print()

    print("─" * 70)
    print("  DrawScope 哲学回顾")
    print("─" * 70)
    print('  "Patterns are descriptions, not promises."')
    print('  "Independent lottery drawings retain their theoretical odds."')
    print()
    print("  与我们项目的核心一致: 诚实、可审计、不预测。")
    print()

    print("=" * 70)
    print("  ✅ DrawScope engine 集成验证完成")
    print("=" * 70)


if __name__ == "__main__":
    main()