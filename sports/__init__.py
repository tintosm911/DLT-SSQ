"""
竞彩实验室 (Sports Betting Lab)
==============================
基于真实体育赛事 + 第三方赔率的量化分析系统

与号码彩的根本区别:
  - 号码彩 (DLT/SSQ): 纯随机事件, 期望必负, 凯利=0
  - 竞彩: 真实赛事 + 市场赔率, 期望可正, 凯利可>0

L3 能力栈:
  1. 赔率反推隐含概率 (去除博彩公司利润)
  2. Elo 球队评分
  3. Value Bet 识别
  4. 凯利仓位 + 资金曲线回测
  5. 组合优化 (多场过关)

数据源:
  - 示例数据 (sample_data/): 5大联赛 2024-2025 完整赛季
  - 第三方爬虫 (data_sources/): 500w / 网易 / 澳客 (异步接入)
"""
__version__ = "0.1.0"

# 子模块按需导入:
#   from sports.config import LEAGUES, MATCH_OUTCOMES
#   from sports.models import Match, Odds, TeamRating, Bet, BetResult
#   from sports.models.elo_system import EloSystem
#   from sports.strategies import find_value_bets, backtest_kelly, find_best_parlays
#   from sports.data_sources import DataSourceRouter
#   from sports.sample_data import load_demo_data, generate_demo_data