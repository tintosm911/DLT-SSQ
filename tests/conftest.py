"""pytest fixtures: 共享测试数据"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def sample_onehot():
    """100 期 × 35 个号码的 one-hot 矩阵（确定性）"""
    np.random.seed(42)
    n_periods = 100
    n_range = 35
    onehot = np.zeros((n_periods, n_range), dtype=np.int8)
    for i in range(n_periods):
        nums = np.random.choice(n_range, 5, replace=False)
        onehot[i, nums] = 1
    return onehot


@pytest.fixture
def sample_df():
    """100 期示例 DataFrame"""
    np.random.seed(42)
    n_periods = 100
    rows = []
    for i in range(n_periods):
        nums = sorted(np.random.choice(35, 5, replace=False) + 1)
        backs = sorted(np.random.choice(12, 2, replace=False) + 1)
        rows.append({
            "period": f"TEST{i:04d}",
            "draw_date": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            "front_1": nums[0], "front_2": nums[1], "front_3": nums[2],
            "front_4": nums[3], "front_5": nums[4],
            "back_1": backs[0], "back_2": backs[1],
        })
    return pd.DataFrame(rows)
