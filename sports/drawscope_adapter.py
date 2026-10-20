"""
中国彩种 ↔ DrawScope Drawing 适配层
====================================

DrawScope Drawing schema:
  draw_date:        date
  main_numbers:     list[int]   (MinLen=1, 无上限)
  special_number:   int | None
  multiplier:       int | None (Powerball 的 Power Play 倍数)

中国彩种映射:
  DLT (前 5 + 后 2):
    main_numbers = [5 个前区]
    special_number = 后区 1 号
    multiplier     = 后区 2 号 (复用 DrawScope 字段)

  SSQ (红 6 + 蓝 1):
    main_numbers = [6 个红球]
    special_number = 蓝球
    multiplier     = None
"""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "third_party"))

from drawscope_engine.protocol.models import Drawing

from data import load_lottery_data


# ============================================================
# DLT 适配
# ============================================================
def dlt_row_to_drawing(row, period: str = None) -> Drawing:
    """
    单行 DLT 数据 → DrawScope Drawing

    Args:
        row: 一行 dict-like (有 front_1..5 和 back_1..2 列)
        period: 期号 (可选, 仅日志)
    """
    front = [int(row[f"front_{i}"]) for i in range(1, 6)]
    back = sorted([int(row[f"back_{i}"]) for i in range(1, 3)])
    return Drawing(
        draw_date=_to_date(row.get("draw_date")),
        main_numbers=front,
        special_number=back[0],
        multiplier=back[1],
    )


def dlt_df_to_drawings(df, max_count: Optional[int] = None) -> List[Drawing]:
    """DLT DataFrame → DrawScope Drawings list"""
    drawings = []
    for _, row in df.iterrows():
        try:
            drawings.append(dlt_row_to_drawing(row))
        except Exception:
            continue
        if max_count and len(drawings) >= max_count:
            break
    return drawings


# ============================================================
# SSQ 适配
# ============================================================
def ssq_row_to_drawing(row) -> Drawing:
    """单行 SSQ → DrawScope Drawing"""
    red = [int(row[f"front_{i}"]) for i in range(1, 7)]
    blue = int(row["back_1"])
    return Drawing(
        draw_date=_to_date(row.get("draw_date")),
        main_numbers=red,
        special_number=blue,
        multiplier=None,
    )


def ssq_df_to_drawings(df, max_count: Optional[int] = None) -> List[Drawing]:
    """SSQ DataFrame → DrawScope Drawings list"""
    drawings = []
    for _, row in df.iterrows():
        try:
            drawings.append(ssq_row_to_drawing(row))
        except Exception:
            continue
        if max_count and len(drawings) >= max_count:
            break
    return drawings


# ============================================================
# 解码辅助 (从 Drawing 反推)
# ============================================================
def decode_dlt(d: Drawing) -> dict:
    """从 DrawScope Drawing 解码回 DLT 格式"""
    return {
        "draw_date": d.draw_date,
        "front": list(d.main_numbers),
        "back": sorted([d.special_number, d.multiplier]) if d.multiplier else [d.special_number],
    }


def decode_ssq(d: Drawing) -> dict:
    """从 DrawScope Drawing 解码回 SSQ 格式"""
    return {
        "draw_date": d.draw_date,
        "front": list(d.main_numbers),  # 6 个红球
        "back": [d.special_number],    # 1 个蓝球
    }


# ============================================================
# Payload 构造 (DrawScope analyze 输入)
# ============================================================
def dlt_payload(drawings: List[Drawing], target_date: Optional[date] = None) -> "AnalysisPayload":
    """构造 DLT 风格的 AnalysisPayload

    注意: DrawScope 假定 0 或 1 个 special number.
    DLT 后区 2 个号 → special_number 存后区 1, multiplier 存后区 2
    """
    from drawscope_engine.protocol.models import AnalysisPayload

    return AnalysisPayload(
        game_id="dlt-cn",
        era_id="dlc-csport",
        main_min=1,
        main_max=35,
        draw_count=5,
        special_min=1,
        special_max=12,
        special_draw_count=1,  # DrawScope 只认 1 个 (后区 2 存 multiplier)
        ordered=False,
        target_draw_date=target_date,
        draws=drawings,
    )


def ssq_payload(drawings: List[Drawing], target_date: Optional[date] = None) -> "AnalysisPayload":
    """构造 SSQ 风格的 AnalysisPayload"""
    from drawscope_engine.protocol.models import AnalysisPayload

    return AnalysisPayload(
        game_id="ssq-cn",
        era_id="ssq-wsport",
        main_min=1,
        main_max=33,
        draw_count=6,
        special_min=1,
        special_max=16,
        special_draw_count=1,
        ordered=False,
        target_draw_date=target_date,
        draws=drawings,
    )


# ============================================================
# 辅助
# ============================================================
def _to_date(value) -> date:
    """string/datetime/date → date"""
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):  # datetime / Timestamp
        try:
            return value.date()
        except Exception:
            pass
    s = str(value)
    # YYYY-MM-DD
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except Exception:
            pass
    return date.today()


# ============================================================
# 一键调用 (从项目数据直接分析)
# ============================================================
def analyze_dlt_from_db(target_date: Optional[date] = None, max_drawings: int = 5000):
    """
    从数据库加载 DLT 数据, 跑 DrawScope analyze, 返回完整 AnalysisResult

    Args:
        target_date: 目标日期 (分析该日期前所有数据)
        max_drawings: 最多用多少期 (避免太大超时)
    """
    from drawscope_engine.statistics.analytics import analyze

    df = load_lottery_data(game="dlt")
    drawings = dlt_df_to_drawings(df, max_count=max_drawings)
    payload = dlt_payload(drawings, target_date=target_date)
    return analyze(payload)


def analyze_ssq_from_db(target_date: Optional[date] = None, max_drawings: int = 5000):
    """从数据库加载 SSQ 数据, 跑 DrawScope analyze"""
    from drawscope_engine.statistics.analytics import analyze

    df = load_lottery_data(game="ssq")
    drawings = ssq_df_to_drawings(df, max_count=max_drawings)
    payload = ssq_payload(drawings, target_date=target_date)
    return analyze(payload)