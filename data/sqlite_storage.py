"""
SQLite 存储 - 多彩种开奖数据持久化
====================================

支持彩种:
  - 大乐透 (dlt)
  - 双色球 (ssq)
  - 可扩展 (PRIZE_RULES 已有)

特性:
  - 自动建表 + schema 迁移
  - UNIQUE 约束 (period, game) 防重复
  - meta 表存元数据 (版本/最后更新时间等)
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / "data-raw"
DATA_NORMALIZED = PROJECT_ROOT / "data-normalized"
DB_PATH = DATA_RAW / "lottery.db"


@dataclass
class Draw:
    """一条开奖记录"""
    period: str             # 期号 (字符串, 大乐透 "26091", 双色球 "2026014")
    draw_date: str          # 开奖日期 (YYYY-MM-DD)
    game: str = "dlt"       # 彩种
    front: List[int] = field(default_factory=list)   # 前区号码
    back: List[int] = field(default_factory=list)    # 后区号码
    prize_money: Optional[float] = None    # 奖池
    sales: Optional[float] = None          # 销量
    notes: Optional[str] = None            # 备注


class SQLiteStorage:
    """SQLite 多彩种存储"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS draws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT NOT NULL,
        game TEXT NOT NULL DEFAULT 'dlt',
        draw_date TEXT NOT NULL,
        front_numbers TEXT NOT NULL,
        back_numbers TEXT NOT NULL,
        front_count INTEGER NOT NULL DEFAULT 5,
        back_count INTEGER NOT NULL DEFAULT 2,
        prize_money REAL,
        sales REAL,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(period, game)
    );
    CREATE INDEX IF NOT EXISTS idx_draws_game ON draws(game);
    CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date);

    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        """初始化表结构"""
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    # ============================================================
    # 增删改查
    # ============================================================
    def save_draws(self, draws: List[Draw]) -> int:
        """批量保存, 返回成功条数"""
        if not draws:
            return 0
        inserted = 0
        with self._connect() as conn:
            for d in draws:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO draws
                           (period, game, draw_date, front_numbers, back_numbers,
                            front_count, back_count, prize_money, sales, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            d.period,
                            d.game,
                            d.draw_date,
                            json.dumps(d.front),
                            json.dumps(d.back),
                            len(d.front),
                            len(d.back),
                            d.prize_money,
                            d.sales,
                            d.notes,
                        ),
                    )
                    inserted += 1
                except Exception as e:
                    logger.warning(f"保存 {d.period} 失败: {e}")
            conn.commit()
        return inserted

    def period_exists(self, period: str, game: str = "dlt") -> bool:
        """检查期号是否存在"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM draws WHERE period=? AND game=? LIMIT 1",
                (period, game),
            ).fetchone()
            return row is not None

    def get_count(self, game: str = None) -> int:
        """总条数"""
        with self._connect() as conn:
            if game:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM draws WHERE game=?", (game,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM draws").fetchone()
            return row["c"]

    def get_latest_period(self, game: str = "dlt") -> Optional[str]:
        """最新期号"""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT period FROM draws WHERE game=?
                   ORDER BY draw_date DESC, period DESC LIMIT 1""",
                (game,),
            ).fetchone()
            return row["period"] if row else None

    def get_oldest_period(self, game: str = "dlt") -> Optional[str]:
        """最早期号"""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT period FROM draws WHERE game=?
                   ORDER BY draw_date ASC, period ASC LIMIT 1""",
                (game,),
            ).fetchone()
            return row["period"] if row else None

    def get_latest_draw(self, game: str = "dlt") -> Optional[Draw]:
        """获取最新一条"""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM draws WHERE game=?
                   ORDER BY draw_date DESC, period DESC LIMIT 1""",
                (game,),
            ).fetchone()
            return self._row_to_draw(row) if row else None

    def load_all(self, game: str = "dlt") -> List[Draw]:
        """加载某彩种全部"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM draws WHERE game=? ORDER BY draw_date ASC, period ASC",
                (game,),
            ).fetchall()
            return [self._row_to_draw(r) for r in rows]

    def load_dataframe(self, game: str = "dlt") -> "pd.DataFrame":
        """加载为 DataFrame (含展平的 front_N / back_N 列)"""
        import pandas as pd
        draws = self.load_all(game=game)
        if not draws:
            return pd.DataFrame()

        rows = []
        for d in draws:
            row = {
                "period": d.period,
                "draw_date": d.draw_date,
                "game": d.game,
            }
            for i, n in enumerate(d.front):
                row[f"front_{i+1}"] = n
            for i, n in enumerate(d.back):
                row[f"back_{i+1}"] = n
            rows.append(row)
        return pd.DataFrame(rows)

    def migrate_from_csv(self, csv_path: str, game: str = "dlt") -> int:
        """从 CSV 迁移到 SQLite (一次性导入)"""
        import pandas as pd
        df = pd.read_csv(csv_path)
        draws = []
        for _, row in df.iterrows():
            period = str(row.get("period", ""))
            draw_date = str(row.get("draw_date", ""))
            front_cols = [c for c in row.index if c.startswith("front_")]
            back_cols = [c for c in row.index if c.startswith("back_")]
            front = [int(row[c]) for c in sorted(front_cols) if pd.notna(row[c])]
            back = [int(row[c]) for c in sorted(back_cols) if pd.notna(row[c])]
            draws.append(Draw(
                period=period,
                draw_date=draw_date,
                game=game,
                front=front,
                back=back,
            ))
        return self.save_draws(draws)

    def _row_to_draw(self, row) -> Optional[Draw]:
        if row is None:
            return None
        try:
            front = json.loads(row["front_numbers"]) if row["front_numbers"] else []
            back = json.loads(row["back_numbers"]) if row["back_numbers"] else []
        except Exception:
            front, back = [], []
        return Draw(
            period=row["period"],
            game=row["game"],
            draw_date=row["draw_date"],
            front=front,
            back=back,
            prize_money=row["prize_money"],
            sales=row["sales"],
            notes=row["notes"],
        )

    # ============================================================
    # Meta 表
    # ============================================================
    def set_meta(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), datetime.now().isoformat()),
            )
            conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else None

    # ============================================================
    # 运维
    # ============================================================
    def health_check(self) -> bool:
        """健康检查: 能查数据"""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
                return self.get_count() >= 0
        except Exception as e:
            logger.warning(f"健康检查失败: {e}")
            return False

    def vacuum(self) -> None:
        """VACUUM (压缩数据库)"""
        with self._connect() as conn:
            conn.execute("VACUUM")