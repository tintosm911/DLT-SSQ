"""
示例数据生成器
==============

⚠️ 当前为基于真实球队 + 合理赛果分布的模拟数据
   真实赔率/赛果需接入爬虫后替换

5大联赛 2024-2025 赛季, 每联赛前 19 轮 ≈ 76 场, 共 ~380 场
"""
from .generator import generate_demo_data, save_demo_data, load_demo_data

__all__ = ["generate_demo_data", "save_demo_data", "load_demo_data"]