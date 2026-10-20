"""
Data 模块入口 - 暴露核心数据访问 API
"""
from .games import (
    GAMES,
    GameConfig,
    get_game,
    get_prize_rules,
    list_games,
)
from .sqlite_storage import SQLiteStorage, Draw

import os
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / "data-raw"
DATA_NORMALIZED = PROJECT_ROOT / "data-normalized"
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_NORMALIZED.mkdir(parents=True, exist_ok=True)

# 兼容性别名
DATA_DIR = DATA_RAW
STORAGE_DIR = DATA_RAW

# 尝试加载 SQLite 数据库路径
DB_PATH = DATA_RAW / "lottery.db"


def load_lottery_data(
    game: str = "dlt",
    source: Optional[str] = None,
    n_periods: Optional[int] = None,
) -> pd.DataFrame:
    """
    加载彩票历史数据 (优先从 SQLite, fallback 到 CSV)

    Args:
        game: 彩种 (dlt=大乐透, ssq=双色球)
        source: 数据源 (sqlite / csv / auto)
        n_periods: 只取最近 N 期 (None=全部)
    """
    if source is None:
        source = "auto"

    # 优先 SQLite
    if source in ("auto", "sqlite") and DB_PATH.exists():
        try:
            storage = SQLiteStorage(db_path=str(DB_PATH))
            df = storage.load_dataframe(game=game)
            if df is not None and len(df) > 0:
                if n_periods is not None:
                    df = df.tail(n_periods).reset_index(drop=True)
                return df
        except Exception as e:
            logger.warning(f"SQLite 加载失败: {e}, fallback 到 CSV")

    # Fallback CSV
    csv_map = {
        "dlt": DATA_RAW / "lottery_history.csv",
        "ssq": DATA_RAW / "ssq_history.csv",
    }
    csv_path = csv_map.get(game)
    if csv_path is None or not csv_path.exists():
        raise FileNotFoundError(
            f"未找到 {game} 数据 (SQLite 和 CSV 都没有). "
            "请先运行 fetch / update 命令."
        )

    df = pd.read_csv(csv_path)
    if n_periods is not None:
        df = df.tail(n_periods).reset_index(drop=True)
    return df


__all__ = [
    "GAMES",
    "GameConfig",
    "get_game",
    "get_prize_rules",
    "list_games",
    "SQLiteStorage",
    "Draw",
    "load_lottery_data",
    "PROJECT_ROOT",
    "DATA_RAW",
    "DATA_NORMALIZED",
    "DB_PATH",
]