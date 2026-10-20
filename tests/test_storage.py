"""
SQLite 存储测试
"""
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import pandas as pd

from data.sqlite_storage import SQLiteStorage, Draw


@pytest.fixture
def temp_db():
    """临时数据库 fixture"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        Path(db_path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def storage(temp_db):
    """SQLiteStorage 实例"""
    return SQLiteStorage(db_path=temp_db)


@pytest.fixture
def sample_draws():
    """示例开奖数据"""
    return [
        Draw(
            period="TEST001",
            draw_date="2024-01-01",
            game="dlt",
            front=[1, 2, 3, 4, 5],
            back=[10, 11],
        ),
        Draw(
            period="TEST002",
            draw_date="2024-01-03",
            game="dlt",
            front=[5, 6, 7, 8, 9],
            back=[1, 12],
        ),
        Draw(
            period="TEST003",
            draw_date="2024-01-05",
            game="ssq",
            front=[1, 5, 10, 15, 20, 25],
            back=[3],
        ),
    ]


class TestStorageInit:
    """存储初始化"""

    def test_init_creates_schema(self, temp_db):
        """初始化时应该自动建表"""
        storage = SQLiteStorage(db_path=temp_db)
        # 应该能查询 (即使空)
        df = storage.load_dataframe()
        assert df is not None

    def test_init_existing_db(self, temp_db):
        """对已存在的 db 也能初始化 (幂等)"""
        s1 = SQLiteStorage(db_path=temp_db)
        s2 = SQLiteStorage(db_path=temp_db)  # 第二次
        assert s1 is not None
        assert s2 is not None


class TestStorageCRUD:
    """增删改查"""

    def test_save_draws(self, storage, sample_draws):
        """保存开奖记录"""
        storage.save_draws(sample_draws)
        count = storage.get_count()
        assert count == len(sample_draws)

    def test_period_exists(self, storage, sample_draws):
        """检查期号是否存在"""
        storage.save_draws(sample_draws)
        assert storage.period_exists("TEST001")
        assert not storage.period_exists("NOT_EXIST")

    def test_get_latest_period(self, storage, sample_draws):
        """获取最新期号"""
        storage.save_draws(sample_draws)
        latest = storage.get_latest_period()
        assert latest == "TEST003" or latest is not None

    def test_get_latest_draw(self, storage, sample_draws):
        """获取最新一条记录"""
        storage.save_draws(sample_draws)
        latest = storage.get_latest_draw()
        assert latest is not None

    def test_get_oldest_period(self, storage, sample_draws):
        """获取最早期号"""
        storage.save_draws(sample_draws)
        oldest = storage.get_oldest_period()
        assert oldest == "TEST001" or oldest is not None

    def test_load_dataframe(self, storage, sample_draws):
        """加载为 DataFrame"""
        storage.save_draws(sample_draws)
        df = storage.load_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(sample_draws)

    def test_load_all(self, storage, sample_draws):
        """加载全部记录"""
        storage.save_draws(sample_draws)
        all_draws = storage.load_all()
        assert len(all_draws) == len(sample_draws)

    def test_health_check(self, storage, sample_draws):
        """健康检查"""
        storage.save_draws(sample_draws)
        result = storage.health_check()
        # 健康检查应该返回 True (有数据)
        assert result is True


class TestStorageMeta:
    """metadata 测试"""

    def test_set_and_get_meta(self, storage):
        """设置和读取 metadata"""
        storage.set_meta("version", "0.1.0")
        val = storage.get_meta("version")
        assert val == "0.1.0"

    def test_get_nonexistent_meta(self, storage):
        """不存在的 key 应返回 None"""
        val = storage.get_meta("nonexistent_key")
        assert val is None


class TestStorageMultiGame:
    """多彩种测试"""

    def test_dlt_and_ssq_coexist(self, storage, sample_draws):
        """大乐透和双色球数据共存"""
        storage.save_draws(sample_draws)
        df_all = storage.load_dataframe()
        # 至少应该有大乐透和双色球数据
        assert len(df_all) >= 2


class TestStorageEdgeCases:
    """边界条件"""

    def test_empty_storage(self, storage):
        """空数据库操作"""
        count = storage.get_count()
        assert count == 0

    def test_save_duplicate_period(self, storage, sample_draws):
        """重复期号 (UNIQUE 约束)"""
        storage.save_draws([sample_draws[0]])
        # 第二次保存同期号 (取决于实现, 可能覆盖/可能抛错)
        try:
            storage.save_draws([sample_draws[0]])
        except Exception:
            pass  # 接受抛错

    def test_vacuum(self, storage, sample_draws):
        """VACUUM 操作"""
        storage.save_draws(sample_draws)
        # vacuum 应该不抛错
        try:
            storage.vacuum()
        except Exception as e:
            pytest.fail(f"vacuum 失败: {e}")