"""
官方数据源基础定义
==================
2026-10-22 重写: 原文件内容整体损坏 (全 null bytes), 从调用方反推 API 重构.
2026-10-31 修正: 原来把**福彩**接口当成了体彩接口 —— URL 和彩种编号都是福彩的,
  但调用方 (data_source.OfficialSource) 把它当"大乐透官方 API"用, 实测直接崩.
  → 现在把两个域的接口彻底分开.

提供:
  - Draw        : 一期开奖的统一数据结构 (含 game 字段, 可直接入 SQLite)
  - URL_SPORTTERY / GAME_NO_DLT : 中国体彩官方接口 (大乐透)
  - URL_CWL               : 中国福彩官方接口 (双色球)
  - PAGE_SIZE   : 分页大小

调用方 (data/data_source.py, data/heat_comparator.py, data/pusher.py, main.py)
依赖的 Draw 字段: period, draw_date, game, front, back
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ============================================================
# 中国体育彩票官方接口 (大乐透)
# ------------------------------------------------------------
# 历史开奖列表: 支持分页, 实测 total = 2941 (2026-10-31)
#   gameNo=85 是体彩的彩种编号 (大乐透)
# ============================================================
URL_SPORTTERY = ('https://webapi.sporttery.cn/gateway/lottery/'
                 'getHistoryPageListV1.qry')
URL_SPORTTERY_LATEST = ('https://webapi.sporttery.cn/gateway/lottery/'
                         'getDigitalDrawInfoV1.qry')

# 大乐透在体彩接口里的彩种编号
GAME_NO_DLT = '85'

# ============================================================
# 中国福利彩票官方接口 (双色球)
# ============================================================
URL_CWL = ('https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/'
           'findDrawNotice')

# ★ 兼容别名: 历史上 URL_OFFICIAL 指向福彩接口, 保留以免打断旧调用方,
#   但新代码请显式用 URL_SPORTTERY / URL_CWL, 别再混用.
URL_OFFICIAL = URL_CWL

# 分页大小
PAGE_SIZE = 30


@dataclass
class Draw:
    """
    一期开奖结果.

    front / back 是**排序后的号码列表**, 方便直接做集合运算和比对.
    game 是彩种代号 ('dlt' / 'ssq'), 入库时需要.
    """

    period: str
    draw_date: str
    game: str = 'dlt'
    front: List[int] = field(default_factory=list)
    back: List[int] = field(default_factory=list)
    prize: Optional[str] = None
    sales: Optional[str] = None
    pool: Optional[str] = None
    content: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # ---- 便捷属性 ----
    @property
    def front_str(self) -> str:
        return ' '.join(f'{n:02d}' for n in self.front)

    @property
    def back_str(self) -> str:
        return ' '.join(f'{n:02d}' for n in self.back)

    @property
    def front_set(self) -> set:
        return set(self.front)

    @property
    def back_set(self) -> set:
        return set(self.back)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'period': self.period,
            'draw_date': self.draw_date,
            'game': self.game,
            'front': list(self.front),
            'back': list(self.back),
            'prize': self.prize,
            'sales': self.sales,
            'pool': self.pool,
        }

    def __str__(self) -> str:
        return (f'{self.period} ({self.draw_date}) '
                f'前 {self.front_str} 后 {self.back_str}')


__all__ = ['Draw', 'URL_SPORTTERY', 'URL_SPORTTERY_LATEST', 'URL_CWL',
           'URL_OFFICIAL', 'GAME_NO_DLT', 'PAGE_SIZE']
