"""
下一期预测 - 综合所有算法的推荐
"""
from __future__ import annotations
from typing import List, Dict, Optional

import numpy as np
import pandas as pd

from core import compute_all_heat_scores


def predict_next(
    df: pd.DataFrame,
    game: str = "dlt",
    n_front: int = None,
    n_back: int = None,
    top_k_front: int = 7,
    top_k_back: int = 3,
    window: int = 100,
) -> Dict[str, List[int]]:
    """
    预测下一期号码

    Returns:
        {
            "front": [号码1, 号码2, ...],
            "back": [号码1, 号码2],
            "front_scores": {号码: 分数},
            "back_scores": {号码: 分数},
            "method": 综合算法名,
        }
    """
    if game == "dlt":
        n_front = n_front or 5
        n_back = n_back or 2
    elif game == "ssq":
        n_front = n_front or 6
        n_back = n_back or 1
    else:
        raise ValueError(f"未知彩种: {game}")

    n_range_front = 35 if game == "dlt" else 33
    n_range_back = 12 if game == "dlt" else 16

    # 前区
    front_cols = [c for c in df.columns if c.startswith("front_")]
    front_onehot = np.zeros((len(df), n_range_front), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(front_onehot, nums[:, None], 1, axis=1)

    front_scores = compute_all_heat_scores(front_onehot, n_range_front, window=window)
    front_composite = front_scores["composite"]

    # 后区
    back_cols = [c for c in df.columns if c.startswith("back_")]
    back_onehot = np.zeros((len(df), n_range_back), dtype=np.int8)
    for col in back_cols:
        nums = df[col].values - 1
        np.put_along_axis(back_onehot, nums[:, None], 1, axis=1)

    back_scores = compute_all_heat_scores(back_onehot, n_range_back, window=window)
    back_composite = back_scores["composite"]

    # 取 Top K
    front_top = np.argsort(front_composite)[::-1][:top_k_front]
    back_top = np.argsort(back_composite)[::-1][:top_k_back]

    return {
        "game": game,
        "front": sorted([int(x) + 1 for x in front_top]),
        "back": sorted([int(x) + 1 for x in back_top]),
        "front_scores": {int(i + 1): float(front_composite[i]) for i in front_top},
        "back_scores": {int(i + 1): float(back_composite[i]) for i in back_top},
        "method": "composite",
    }