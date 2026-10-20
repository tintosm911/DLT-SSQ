"""
推送模块 - 新开奖通知
支持渠道：
  - console: 控制台打印（默认）
  - file: 写入本地日志文件
  - webhook: POST 到任意 HTTP 端点（钉钉/企微/Telegram 通用）
  - dingtalk: 钉钉机器人（签名版）
  - wecom: 企业微信机器人
  - telegram: Telegram Bot

用法:
    from data import DataFetcher, PushNotifier

    fetcher = DataFetcher()
    notifier = PushNotifier(channels=[
        {"type": "console"},
        {"type": "file", "path": "logs/push.log"},
        {"type": "dingtalk", "webhook": "https://oapi.dingtalk.com/robot/send?access_token=...", "secret": "SEC..."},
    ])

    fetcher.poll_for_new_draws(
        on_new_draw=notifier.notify,
        interval_seconds=120,
    )
"""
from __future__ import annotations
import os
import sys
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
from dataclasses import dataclass

# 禁用系统代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

import requests

from .data_fetcher import Draw
from .heat_comparator import HeatComparator, HitReport
from .image_uploader import ImageUploader, UploadResult

logger = logging.getLogger(__name__)


@dataclass
class PushConfig:
    """推送配置"""
    type: str                       # 渠道类型
    enabled: bool = True
    # 各渠道参数
    path: Optional[str] = None                  # file
    webhook: Optional[str] = None                # webhook / dingtalk / wecom
    secret: Optional[str] = None                 # dingtalk 签名密钥
    bot_token: Optional[str] = None              # telegram bot token
    chat_id: Optional[str] = None                # telegram chat id
    headers: Optional[Dict[str, str]] = None     # webhook 自定义 header
    template: Optional[str] = None               # 自定义模板（可选）
    # 图片相关
    include_image: bool = False                  # 是否附带热度 PNG
    image_path: Optional[str] = None             # 指定的图片路径（否则自动生成）


class PushNotifier:
    """
    推送通知器 - 多渠道聚合
    notify(draw, is_first) 是统一入口
    """

    def __init__(self, channels: List[Dict[str, Any]] = None, config_path: Path = None, enable_hit_report: bool = True):
        """
        channels: 渠道配置列表，每项形如 {"type": "console"} 或 {"type": "dingtalk", "webhook": "..."}
        config_path: YAML 配置文件路径，覆盖默认
        enable_hit_report: 是否启用命中评估（新开奖到达时自动算"按热度选 Top-K vs 实际"）
        """
        self.channels: List[PushConfig] = []
        self.enable_hit_report = enable_hit_report
        self.comparator = HeatComparator() if enable_hit_report else None
        self.handlers: Dict[str, Callable[[Draw, bool], None]] = {
            "console": self._push_console,
            "file": self._push_file,
            "webhook": self._push_webhook,
            "dingtalk": self._push_dingtalk,
            "wecom": self._push_wecom,
            "telegram": self._push_telegram,
        }

        # 加载配置
        if config_path and Path(config_path).exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            channels = cfg.get("push", {}).get("channels", channels or [])
        elif channels is None:
            channels = [{"type": "console"}]

        for c in channels:
            cfg = PushConfig(**{k: v for k, v in c.items() if k in PushConfig.__annotations__})
            self.channels.append(cfg)

        logger.info(f"推送器初始化完成，启用渠道: {[c.type for c in self.channels]}")

    def notify(self, draw: Draw, is_first: bool = False, image_path: Optional[str] = None) -> None:
        """
        统一通知入口
        is_first=True 表示首次（不是真正新开奖），可用于显示"启动"提示
        image_path: 可选，附带图片路径（PNG），会自动上传到图床
        """
        # 计算命中评估（仅对新开奖，不是首次）
        hit_report: Optional[HitReport] = None
        if self.enable_hit_report and not is_first and self.comparator:
            try:
                hit_report = self.comparator.evaluate_new_draw(draw)
            except Exception as e:
                logger.error(f"命中评估失败: {e}")

        # 如果有任何渠道需要图片，先上传
        image_url: Optional[str] = None
        if image_path and any(c.include_image for c in self.channels if c.enabled):
            uploader = ImageUploader()
            result = uploader.upload(Path(image_path))
            if result.success:
                image_url = result.url
                logger.info(f"图片已上传: {image_url}")
            else:
                logger.warning(f"图片上传失败（{result.error}），消息中不带图")

        for ch in self.channels:
            if not ch.enabled:
                continue
            handler = self.handlers.get(ch.type)
            if not handler:
                logger.warning(f"未知推送渠道: {ch.type}")
                continue
            try:
                handler(ch, draw, is_first, hit_report, image_url)
            except Exception as e:
                logger.error(f"推送渠道 {ch.type} 失败: {e}")

    # ----------------------------------------------------------
    # 各渠道实现
    # ----------------------------------------------------------

    def _format_message(self, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None) -> Dict[str, str]:
        """统一格式化消息"""
        front_str = " ".join(f"{n:02d}" for n in draw.front)
        back_str = " ".join(f"{n:02d}" for n in draw.back)

        if is_first:
            title = f"📊 监控启动 - 当前最新期 {draw.period}"
        else:
            title = f"🎯 新开奖！第 {draw.period} 期"

        result = {
            "title": title,
            "period": draw.period,
            "date": draw.draw_date,
            "front": front_str,
            "back": back_str,
            "front_list": " ".join(f"{n:02d}" for n in draw.front),
            "back_list": " ".join(f"{n:02d}" for n in draw.back),
        }

        # 命中评估（如果有）
        if hit_report and not is_first:
            hit_msg = self.comparator.format_report(hit_report)
            result["hit_title"] = hit_msg["title"]
            result["hit_front"] = hit_msg["front_section"]
            result["hit_back"] = hit_msg["back_section"]
            result["hit_distribution"] = hit_msg["distribution"]
            result["hit_summary"] = hit_msg["summary"]
        else:
            result["hit_title"] = ""
            result["hit_front"] = ""
            result["hit_back"] = ""
            result["hit_distribution"] = ""
            result["hit_summary"] = ""

        return result

    def _push_console(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None) -> None:
        """控制台输出"""
        msg = self._format_message(draw, is_first, hit_report)
        prefix = "[启动]" if is_first else "[新开奖]"
        print(f"\n{'=' * 70}")
        print(f"{prefix} {msg['title']}")
        print(f"{'─' * 70}")
        print(f"  期号: {msg['period']}    日期: {msg['date']}")
        print(f"  前区: {msg['front']}")
        print(f"  后区: {msg['back']}")
        if hit_report and not is_first:
            print(f"{'─' * 70}")
            print(f"  📊 热度策略命中评估")
            print(f"  前区 Top-{hit_report.front_top_k} 命中 {hit_report.front_hit_count}/5")
            print(f"    选号: {' '.join(f'{n:02d}' for n in hit_report.front_pick)}")
            print(f"    实际: {msg['front']}")
            if hit_report.front_hits:
                print(f"    命中: {' '.join(f'{n:02d}' for n in hit_report.front_hits)}")
            print(f"  后区 Top-{hit_report.back_top_k} 命中 {hit_report.back_hit_count}/{hit_report.back_top_k}")
            print(f"    选号: {' '.join(f'{n:02d}' for n in hit_report.back_pick)}")
            print(f"    实际: {msg['back']}")
            if hit_report.back_hits:
                print(f"    命中: {' '.join(f'{n:02d}' for n in hit_report.back_hits)}")
            dist = hit_report.front_actual_hot_warm_cold
            print(f"  实际开奖热度分布: 热{dist['hot']} 温{dist['warm']} 冷{dist['cold']}")
        print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 70}\n")
        sys.stdout.flush()

    def _push_file(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None) -> None:
        """写入文件日志"""
        path = Path(cfg.path or "logs/push.log")
        path.parent.mkdir(parents=True, exist_ok=True)

        msg = self._format_message(draw, is_first, hit_report)
        prefix = "START" if is_first else "NEW"

        line = (
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{prefix}] "
            f"period={msg['period']} date={msg['date']} "
            f"front={msg['front']} back={msg['back']}"
        )
        if hit_report and not is_first:
            line += (
                f" | HIT: front={hit_report.front_hit_count}/5 "
                f"back={hit_report.back_hit_count}/{hit_report.back_top_k} "
                f"summary={hit_report.summary}"
            )
        line += "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def _push_webhook(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None) -> None:
        """通用 webhook POST"""
        if not cfg.webhook:
            logger.warning("webhook 渠道缺少 webhook URL")
            return

        msg = self._format_message(draw, is_first, hit_report)
        payload = {
            "title": msg["title"],
            "period": msg["period"],
            "draw_date": msg["date"],
            "front": msg["front_list"],
            "back": msg["back_list"],
            "is_first": is_first,
            "timestamp": int(time.time()),
        }
        if hit_report and not is_first:
            payload["hit"] = {
                "front_pick": hit_report.front_pick,
                "front_hits": hit_report.front_hits,
                "front_hit_count": hit_report.front_hit_count,
                "back_pick": hit_report.back_pick,
                "back_hits": hit_report.back_hits,
                "back_hit_count": hit_report.back_hit_count,
                "summary": hit_report.summary,
            }
        headers = cfg.headers or {"Content-Type": "application/json"}
        resp = requests.post(cfg.webhook, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info(f"webhook 推送成功: {cfg.webhook[:50]}...")

    def _push_dingtalk(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None, image_url: Optional[str] = None) -> None:
        """钉钉机器人（支持签名）"""
        if not cfg.webhook:
            logger.warning("dingtalk 渠道缺少 webhook URL")
            return

        msg = self._format_message(draw, is_first, hit_report)
        text = (
            f"### {msg['title']}\n\n"
            f"- **期号**: {msg['period']}\n"
            f"- **开奖日期**: {msg['date']}\n"
            f"- **前区**: `{msg['front']}`\n"
            f"- **后区**: `{msg['back']}`\n"
        )

        if hit_report and not is_first:
            text += (
                f"\n---\n\n"
                f"### 📊 热度策略命中评估\n\n"
                f"{msg['hit_front']}\n\n"
                f"{msg['hit_back']}\n\n"
                f"{msg['hit_distribution']}\n\n"
                f"**{msg['hit_summary']}**\n"
            )

        # 如果有图片 URL，钉钉 markdown 支持 ![](url) 语法
        if image_url:
            text += f"\n---\n\n### 📈 热度热力图\n\n![heatmap]({image_url})\n"

        text += f"\n> 通知时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        # 钉钉签名（可选）
        url = cfg.webhook
        if cfg.secret:
            timestamp = str(round(time.time() * 1000))
            secret_enc = cfg.secret.encode("utf-8")
            string_to_sign = f"{timestamp}\n{cfg.secret}"
            hmac_code = hmac.new(
                secret_enc, string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url = f"{cfg.webhook}&timestamp={timestamp}&sign={sign}"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": msg["title"],
                "text": text,
            },
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"钉钉推送成功")

    def _push_wecom(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None, image_url: Optional[str] = None) -> None:
        """企业微信机器人"""
        if not cfg.webhook:
            logger.warning("wecom 渠道缺少 webhook URL")
            return

        msg = self._format_message(draw, is_first, hit_report)
        content = (
            f"## {msg['title']}\n"
            f"**期号**: {msg['period']}\n"
            f"**开奖日期**: {msg['date']}\n"
            f"**前区**: `{msg['front']}`\n"
            f"**后区**: `{msg['back']}`\n"
        )
        if hit_report and not is_first:
            content += (
                f"\n### 📊 热度策略命中评估\n"
                f"{msg['hit_front']}\n\n"
                f"{msg['hit_back']}\n\n"
                f"{msg['hit_distribution']}\n\n"
                f"**{msg['hit_summary']}**\n"
            )

        if image_url:
            content += f"\n### 📈 热度热力图\n\n![heatmap]({image_url})\n"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        }
        resp = requests.post(cfg.webhook, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"企微推送成功")

    def _push_telegram(self, cfg: PushConfig, draw: Draw, is_first: bool, hit_report: Optional[HitReport] = None, image_url: Optional[str] = None) -> None:
        """Telegram Bot"""
        if not cfg.bot_token or not cfg.chat_id:
            logger.warning("telegram 渠道缺少 bot_token 或 chat_id")
            return

        msg = self._format_message(draw, is_first, hit_report)
        text = (
            f"*{msg['title']}*\n\n"
            f"期号: `{msg['period']}`\n"
            f"日期: {msg['date']}\n"
            f"前区: `{msg['front']}`\n"
            f"后区: `{msg['back']}`\n"
        )
        if hit_report and not is_first:
            text += (
                f"\n*📊 热度策略命中评估*\n"
                f"{msg['hit_front']}\n\n"
                f"{msg['hit_back']}\n\n"
                f"_{msg['hit_summary']}_\n"
            )

        if image_url:
            text += f"\n*📈 热度热力图*: {image_url}\n"

        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        payload = {
            "chat_id": cfg.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Telegram 推送成功")


# ============================================================
# CLI 调试
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = DataFetcher()
    notifier = PushNotifier(channels=[
        {"type": "console"},
        {"type": "file", "path": "logs/push.log"},
    ])

    print("测试推送：拿最新一期...")
    latest = fetcher.get_latest_draw()
    if latest:
        print(f"最新一期: {latest.period} ({latest.draw_date})")
        notifier.notify(latest, is_first=True)
        print("[OK] 推送完成，详见 logs/push.log")
    else:
        print("[FAIL] 获取最新数据失败")
