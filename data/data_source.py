"""
多数据源抽象 - 自动降级，提升长期可用性
==========================================
主源: 中国体彩官方 API (webapi.sporttery.cn)
备用:
  - 500彩票网 (datachart.500.com) - 可能有反爬
  - 体彩官方页 (www.sporttery.cn) - 备用网页解析
  - 福彩 API (www.cwl.gov.cn) - 用于双色球

当主源失败时自动切换到备用源
"""
from __future__ import annotations
import os
import sys
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

# 禁用代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

from .data_fetcher import Draw, URL_OFFICIAL, GAME_NO_DLT, PAGE_SIZE
from .games import get_game

logger = logging.getLogger(__name__)


# ============================================================
# 数据源抽象
# ============================================================
class DataSource(ABC):
    """数据源抽象基类"""

    name: str = "base"
    priority: int = 100

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    @abstractmethod
    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        """拉取单页"""
        ...

    @abstractmethod
    def fetch_latest(self) -> Optional[Draw]:
        """拉取最新一期"""
        ...

    @abstractmethod
    def health(self) -> bool:
        """健康检查"""
        ...


# ============================================================
# 主源：官方 API
# ============================================================
class OfficialSource(DataSource):
    """中国体彩官方 API（已验证可用）"""
    name = "官方API"
    priority = 1  # 最优先

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        params = {
            "gameNo": GAME_NO_DLT,
            "provinceId": "0",
            "pageSize": str(page_size),
            "pageNo": str(page_no),
            "isVerify": "1",
        }
        self.session.headers["Referer"] = "https://www.sporttery.cn/"
        resp = self.session.get(URL_OFFICIAL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            return []

        lst = data.get("value", {}).get("list", [])
        return self._parse_items(lst)

    def fetch_latest(self) -> Optional[Draw]:
        params = {
            "gameNo": GAME_NO_DLT,
            "provinceId": "0",
            "pageSize": "1",
            "pageNo": "1",
            "isVerify": "1",
        }
        self.session.headers["Referer"] = "https://www.sporttery.cn/"
        resp = self.session.get(URL_OFFICIAL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            return None

        value = data.get("value", {})
        # 优先 lastPoolDraw
        if value.get("lastPoolDraw"):
            return self._parse_item(value["lastPoolDraw"])
        # 否则 list[0]
        if value.get("list"):
            return self._parse_item(value["list"][0])
        return None

    def health(self) -> bool:
        try:
            d = self.fetch_latest()
            return d is not None
        except Exception as e:
            logger.warning(f"[{self.name}] 健康检查失败: {e}")
            return False

    def _parse_items(self, lst: list) -> List[Draw]:
        return [self._parse_item(item) for item in lst if self._parse_item(item)]

    def _parse_item(self, item: dict) -> Optional[Draw]:
        try:
            period = item.get("lotteryDrawNum", "").strip()
            draw_date = item.get("lotteryDrawTime", "").strip()
            result = item.get("lotteryDrawResult", "").strip()
            if not (period and draw_date and result):
                return None
            nums = [int(x) for x in result.split()]
            if len(nums) != 7:
                return None
            return Draw(
                period=period,
                draw_date=draw_date,
                front=sorted(nums[:5]),
                back=sorted(nums[5:]),
            )
        except (ValueError, KeyError):
            return None


# ============================================================
# 备用源 1：体彩官方辅助 API（核对最新一期）
# ============================================================
class OfficialAuxSource(DataSource):
    """体彩官方辅助 API - 用于核对最新一期

    URL: getDigitalDrawInfoV1.qry
    用途: 与主 API 交叉验证，避免单源错误
    限制: 只能拿最新一期（不能分页拉历史）
    """
    name = "官方辅助API"
    priority = 2
    URL = "https://webapi.sporttery.cn/gateway/lottery/getDigitalDrawInfoV1.qry"

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        raise NotImplementedError("官方辅助 API 只能获取最新一期，不支持分页历史")

    def fetch_latest(self) -> Optional[Draw]:
        params = {"param": "85,0", "isVerify": "1"}
        self.session.headers["Referer"] = "https://www.sporttery.cn/"
        resp = self.session.get(self.URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            return None

        dlt = data.get("value", {}).get("dlt", {})
        if not dlt:
            return None

        try:
            period = str(dlt.get("lotteryDrawNum", "")).strip()
            draw_time = str(dlt.get("lotteryDrawTime", "")).strip()
            result = str(dlt.get("lotteryDrawResult", "")).strip()
            verify = dlt.get("verify", 0)

            # verify=1 表示已审核，是可信数据
            if verify != 1:
                logger.warning(f"官方辅助 API: data not verified (verify={verify})")

            # 时间格式: "2026-10-14 21:18:40" -> "2026-10-14"
            draw_date = draw_time.split(" ")[0] if " " in draw_time else draw_time

            nums = [int(x) for x in result.split()]
            if len(nums) != 7:
                return None

            return Draw(
                period=period,
                draw_date=draw_date,
                front=sorted(nums[:5]),
                back=sorted(nums[5:]),
            )
        except (ValueError, KeyError) as e:
            logger.debug(f"解析失败: {e}")
            return None

    def health(self) -> bool:
        try:
            d = self.fetch_latest()
            return d is not None
        except Exception as e:
            logger.warning(f"[{self.name}] 健康检查失败: {e}")
            return False


# ============================================================
# 备用源 2：体彩官方页（HTML 解析，需要 Selenium）
# ============================================================
class SportteryPageSource(DataSource):
    """体彩官网历史页（HTML 解析，需要 Selenium）"""
    name = "体彩官网页"
    priority = 4
    URL = "https://www.sporttery.cn/dlt/kaijiang/"

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        raise NotImplementedError("体彩官网页用 JS 渲染，需要 Selenium")

    def fetch_latest(self) -> Optional[Draw]:
        return None

    def health(self) -> bool:
        return False  # 暂不可用


# ============================================================
# 备用源 3：500 彩票网（需要绕过反爬）
# ============================================================
class FiveHundredSource(DataSource):
    """500 彩票网（反爬严格，仅作兜底）"""
    name = "500彩票网"
    priority = 5
    URL = "https://datachart.500.com/dlt/history/history.shtml"

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
            "Referer": "https://www.baidu.com/",
        }
        resp = self.session.get(
            self.URL,
            params={"start": page_no, "end": page_no},
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        resp.encoding = "gbk"
        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.find_all("tr", class_="t_tr1")
        draws = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            try:
                period = cells[0].text.strip()
                draw_date = cells[1].text.strip()
                front_text = cells[2].text.strip()
                back_text = cells[3].text.strip()
                front = sorted([int(x) for x in front_text.split(",") if x.strip()])
                back = sorted([int(x) for x in back_text.split(",") if x.strip()])
                if len(front) == 5 and len(back) == 2:
                    draws.append(Draw(
                        period=period, draw_date=draw_date, front=front, back=back,
                    ))
            except (ValueError, IndexError):
                continue
        return draws

    def fetch_latest(self) -> Optional[Draw]:
        draws = self.fetch_page(1, 1)
        return draws[0] if draws else None

    def health(self) -> bool:
        try:
            d = self.fetch_latest()
            return d is not None
        except Exception as e:
            logger.warning(f"[{self.name}] 健康检查失败: {e}")
            return False


# ============================================================
# 双色球数据源（福彩官方）
# ============================================================
class WelfareSSQSource(DataSource):
    """中国福利彩票双色球数据源

    URL: cwl.gov.cn findDrawNotice
    用途: 拉取双色球历史开奖
    限制: 每次只能查单期（通过 issueStart/end 精确查询）
    """
    name = "福彩双色球API"
    priority = 1
    URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE) -> List[Draw]:
        # 双色球 API 不支持分页历史
        # 通过最新期号往回推
        latest = self.fetch_latest()
        if not latest:
            return []
        latest_period_num = int(latest.period)
        # 计算 page_no 对应的期号范围
        start_num = latest_period_num - (page_no * page_size) + 1
        end_num = start_num + page_size - 1
        if start_num < 2003001:  # 双色球 2003 年上市
            return []
        return self._fetch_range(start_num, end_num)

    def fetch_latest(self) -> Optional[Draw]:
        """通过 issueStart/end 都设为 0 让 API 返回最新"""
        # 实际上 findDrawNotice 单期查询，需要知道期号
        # 用 pageSize=1 + 不指定 issueStart 获取最新
        params = {
            "name": "ssq",
            "pageNo": "1",
            "pageSize": "1",
            "systemType": "PC",
        }
        self.session.headers["Referer"] = "https://www.cwl.gov.cn/"
        resp = self.session.get(self.URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_first(data)

    def fetch_period(self, period: str) -> Optional[Draw]:
        """按期号查单期"""
        return self._fetch_range(int(period), int(period))

    def _fetch_range(self, start_num: int, end_num: int) -> List[Draw]:
        """按期号范围批量查询"""
        if start_num > end_num:
            return []
        # 逐期查询（API 限制单期）
        draws = []
        # 一次只查一期，避免太慢
        for period_num in range(start_num, end_num + 1):
            period_str = f"{period_num:07d}"  # 双色球 7 位期号
            params = {
                "name": "ssq",
                "issueStart": period_str,
                "issueEnd": period_str,
                "pageNo": "1",
                "pageSize": "1",
                "systemType": "PC",
            }
            self.session.headers["Referer"] = "https://www.cwl.gov.cn/"
            try:
                resp = self.session.get(self.URL, params=params, timeout=8)
                resp.raise_for_status()
                data = resp.json()
                draw = self._parse_first(data)
                if draw:
                    draws.append(draw)
            except Exception as e:
                logger.debug(f"查 SSQ {period_str} 失败: {e}")
                continue
        return draws

    def _parse_first(self, data: dict) -> Optional[Draw]:
        """解析 findDrawNotice 响应"""
        if data.get("state") != 0:
            return None
        results = data.get("result", [])
        if not results:
            return None
        item = results[0]
        try:
            period = str(item.get("code", "")).strip()
            date = str(item.get("date", "")).strip()
            red_str = item.get("red", "")
            blue_str = item.get("blue", "")
            # 日期格式: "2026-02-01(日)" -> "2026-02-01"
            draw_date = date.split("(")[0] if "(" in date else date

            front = sorted([int(x) for x in red_str.split(",") if x.strip()])
            # blue 可能是 "01" 或 "" + blue2
            back_str = blue_str or item.get("blue2", "")
            back = sorted([int(x) for x in back_str.split(",") if x.strip()])

            # 校验
            from .games import get_game
            cfg = get_game("ssq")
            if len(front) != cfg.front_count or len(back) != cfg.back_count:
                return None
            if not all(1 <= n <= cfg.front_range for n in front):
                return None
            if not all(1 <= n <= cfg.back_range for n in back):
                return None

            return Draw(period=period, draw_date=draw_date, front=front, back=back)
        except (ValueError, KeyError) as e:
            logger.debug(f"SSQ 解析失败: {e}")
            return None

    def health(self) -> bool:
        try:
            d = self.fetch_latest()
            return d is not None
        except Exception as e:
            logger.warning(f"[{self.name}] 健康检查失败: {e}")
            return False


# ============================================================
# 数据源路由器（自动降级）
# ============================================================
class DataSourceRouter:
    """
    多数据源路由器
    - 按优先级尝试
    - 失败时自动切换
    - 记录每个源的可用性
    """

    def __init__(self, sources: List[DataSource] = None, game: str = "dlt"):
        """
        Args:
            sources: 自定义数据源列表
            game: 彩种代号（dlt / ssq）
        """
        if sources is None:
            if game == "ssq":
                sources = [WelfareSSQSource()]
            else:
                # 默认配置：官方主 → 官方辅助 → 500
                sources = [
                    OfficialSource(),       # 主源：getHistoryPageListV1.qry
                    OfficialAuxSource(),    # 辅助：getDigitalDrawInfoV1.qry
                    FiveHundredSource(),    # 兜底：500.com
                ]
        # 按优先级排序
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.game = game
        self.stats = {s.name: {"calls": 0, "successes": 0, "failures": 0, "last_error": None} for s in self.sources}

    def fetch_page(self, page_no: int, page_size: int = PAGE_SIZE, max_retries: int = 2) -> List[Draw]:
        """拉取单页，自动降级"""
        for source in self.sources:
            for attempt in range(max_retries):
                try:
                    self.stats[source.name]["calls"] += 1
                    result = source.fetch_page(page_no, page_size)
                    if result:
                        self.stats[source.name]["successes"] += 1
                        return result
                except Exception as e:
                    self.stats[source.name]["failures"] += 1
                    self.stats[source.name]["last_error"] = str(e)[:200]
                    logger.warning(f"[{source.name}] 第 {attempt + 1} 次失败: {e}")
                    time.sleep(1)

            logger.warning(f"[{source.name}] 已重试 {max_retries} 次，跳过")
            # 进入下一个源

        raise Exception("所有数据源都失败")

    def fetch_latest(self, max_retries: int = 2) -> Optional[Draw]:
        """拉取最新一期，自动降级"""
        for source in self.sources:
            for attempt in range(max_retries):
                try:
                    self.stats[source.name]["calls"] += 1
                    result = source.fetch_latest()
                    if result:
                        self.stats[source.name]["successes"] += 1
                        return result
                except Exception as e:
                    self.stats[source.name]["failures"] += 1
                    self.stats[source.name]["last_error"] = str(e)[:200]
                    logger.warning(f"[{source.name}] 第 {attempt + 1} 次失败: {e}")
                    time.sleep(1)

        logger.error("所有数据源都失败，无法获取最新开奖")
        return None

    def fetch_latest_cross_verified(self, max_retries: int = 2) -> Optional[Draw]:
        """
        拉取最新一期，多源交叉验证
        至少 2 个源都返回相同结果才算可信

        Returns: Draw 或 None
        """
        results = []
        for source in self.sources:
            if not isinstance(source, (OfficialSource, OfficialAuxSource)):
                # 只用官方源交叉验证
                continue
            for attempt in range(max_retries):
                try:
                    self.stats[source.name]["calls"] += 1
                    result = source.fetch_latest()
                    if result:
                        self.stats[source.name]["successes"] += 1
                        results.append(result)
                        break  # 这个源成功
                except Exception as e:
                    self.stats[source.name]["failures"] += 1
                    logger.warning(f"[{source.name}] 验证失败: {e}")
                    time.sleep(1)

        if not results:
            logger.error("无任何源返回最新数据")
            return None

        # 检查所有结果是否一致
        first = results[0]
        for r in results[1:]:
            if r.period != first.period or r.front != first.front or r.back != first.back:
                logger.warning(f"数据冲突! 主源: {first.period} {first.front}+{first.back}, 辅助: {r.period} {r.front}+{r.back}")
                # 返回主源结果但记录警告
                return first

        if len(results) >= 2:
            logger.info(f"✅ 双源验证通过: {first.period} {first.front}+{first.back}")

        return first

    def health_check(self) -> Dict:
        """检查所有源的可用性"""
        result = {}
        for source in self.sources:
            result[source.name] = source.health()
        return result

    def get_stats(self) -> Dict:
        """获取调用统计"""
        return dict(self.stats)


# ============================================================
# CLI 调试
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("  多数据源路由器测试")
    print("=" * 60)

    router = DataSourceRouter()

    print("\n  健康检查:")
    health = router.health_check()
    for name, ok in health.items():
        status = "✅" if ok else "❌"
        print(f"    {status} {name}")

    print("\n  拉取最新一期（双源交叉验证）:")
    latest = router.fetch_latest_cross_verified()
    if latest:
        print(f"    ✅ {latest.period} - {latest.draw_date}")
        print(f"       前区: {latest.front}")
        print(f"       后区: {latest.back}")
    else:
        print("    ❌ 所有源都失败")

    print("\n  拉取首页（pageNo=1）:")
    page = router.fetch_page(1)
    if page:
        print(f"    ✅ 拿到 {len(page)} 期")
        print(f"       最新: {page[0].period}, 最旧: {page[-1].period}")

    print("\n  调用统计:")
    for name, st in router.get_stats().items():
        print(f"    {name}: calls={st['calls']}, successes={st['successes']}, failures={st['failures']}")
