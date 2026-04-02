"""
SENIA Instant — 拍照即出结果, 3秒对色
======================================

颠覆点: 操作员不需要打开网页/App, 直接:
  1. 微信/钉钉/企业微信 发一张照片
  2. 3秒内收到判定结果 + 调色建议
  3. 语音播报: "临界, 偏红偏黄, 建议减红0.5%"

技术实现:
  - HTTP Webhook 接收微信/钉钉消息
  - 异步图像处理队列
  - 结构化结果回复 (文字 + 卡片)
  - 语音合成 TTS (可选)

为什么颠覆: 把"专业工具"变成"聊天机器人",
零学习成本, 每个工人都会用.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import Any


@dataclass
class InstantResult:
    """即时对色结果, 可转为聊天消息."""
    tier: str = ""
    dE00: float = 0.0
    directions: list[str] = field(default_factory=list)
    top_advice: str = ""
    profile: str = ""
    lot_id: str = ""
    elapsed_sec: float = 0.0
    image_url: str = ""
    error: str = ""

    def to_text_message(self) -> str:
        """转为聊天文本消息 (微信/钉钉通用)."""
        if self.error:
            return f"❌ 对色失败: {self.error}"

        tier_emoji = {"PASS": "✅", "MARGINAL": "⚠️", "FAIL": "❌"}.get(self.tier, "❓")
        tier_cn = {"PASS": "合格", "MARGINAL": "临界", "FAIL": "不合格"}.get(self.tier, "未知")

        lines = [
            f"{tier_emoji} 判定: {tier_cn}",
            f"📊 色差: ΔE = {self.dE00:.2f}",
        ]
        if self.directions:
            lines.append(f"🎯 偏差: {', '.join(self.directions)}")
        if self.top_advice:
            lines.append(f"💡 建议: {self.top_advice}")
        if self.lot_id:
            lines.append(f"📋 批次: {self.lot_id}")
        lines.append(f"⏱ 耗时: {self.elapsed_sec:.1f}s")
        return "\n".join(lines)

    def to_voice_text(self) -> str:
        """转为语音播报文本 (给 TTS 引擎)."""
        if self.error:
            return f"对色失败, {self.error}"
        tier_cn = {"PASS": "合格", "MARGINAL": "临界", "FAIL": "不合格"}.get(self.tier, "")
        text = f"判定{tier_cn}, 色差{self.dE00:.1f}"
        if self.directions:
            text += f", {''.join(self.directions)}"
        if self.top_advice:
            text += f", 建议{self.top_advice}"
        return text

    def to_wecom_card(self) -> dict[str, Any]:
        """转为企业微信卡片消息格式."""
        tier_cn = {"PASS": "合格 ✅", "MARGINAL": "临界 ⚠️", "FAIL": "不合格 ❌"}.get(self.tier, "")
        color = {"PASS": "info", "MARGINAL": "warning", "FAIL": "comment"}.get(self.tier, "info")
        return {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "text_notice",
                "main_title": {"title": f"对色结果: {tier_cn}"},
                "sub_title_text": f"ΔE = {self.dE00:.2f} | {', '.join(self.directions) or '正常'}",
                "horizontal_content_list": [
                    {"keyname": "批次", "value": self.lot_id or "-"},
                    {"keyname": "材质", "value": self.profile or "auto"},
                    {"keyname": "建议", "value": self.top_advice or "无需调整"},
                ],
            },
        }

    def to_dingtalk_card(self) -> dict[str, Any]:
        """转为钉钉卡片消息格式."""
        tier_cn = {"PASS": "合格 ✅", "MARGINAL": "临界 ⚠️", "FAIL": "不合格 ❌"}.get(self.tier, "")
        return {
            "msgtype": "actionCard",
            "actionCard": {
                "title": f"SENIA 对色: {tier_cn}",
                "text": self.to_text_message(),
                "singleTitle": "查看详情",
                "singleURL": "",
            },
        }


def process_instant(
    image_bytes: bytes,
    lot_id: str = "",
    profile: str = "auto",
) -> InstantResult:
    """
    核心处理: 从图片字节到即时结果.
    设计为可被任何消息平台调用.
    """
    import cv2
    import numpy as np

    start = time.perf_counter()
    result = InstantResult(lot_id=lot_id, profile=profile)

    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            result.error = "无法解析图片, 请发送JPG/PNG格式"
            return result

        # 调用完整管线
        from senia_image_pipeline import analyze_photo
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp_path = f.name

        report = analyze_photo(
            image_path=tmp_path,
            profile_name=profile,
            lot_id=lot_id,
        )

        Path(tmp_path).unlink(missing_ok=True)

        result.tier = report.get("tier", "UNKNOWN")
        result.dE00 = report.get("result", {}).get("summary", {}).get("avg_delta_e00", 0.0)
        result.directions = report.get("deviation", {}).get("directions", [])
        result.profile = report.get("profile", {}).get("used", "auto")

        advices = report.get("recipe_advice", {}).get("advices", [])
        if advices:
            result.top_advice = advices[0].get("action", "")

    except RuntimeError as e:
        result.error = str(e)
    except Exception as e:
        result.error = f"分析异常: {type(e).__name__}"

    result.elapsed_sec = round(time.perf_counter() - start, 2)
    return result


# ══════════════════════════════════════════════════════════
# 消息平台 Webhook 处理器
# ══════════════════════════════════════════════════════════

class WebhookHandler:
    """
    处理来自微信/钉钉/企业微信的 Webhook 消息.
    解析图片消息 → 下载图片 → 调用 process_instant → 回复结果.
    """

    def __init__(self, reply_url: str = "", platform: str = "wecom") -> None:
        self._reply_url = reply_url
        self._platform = platform

    def handle_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        处理一条传入消息.
        返回应该回复的消息体.
        """
        msg_type = payload.get("msgtype", payload.get("MsgType", ""))
        if msg_type not in ("image", "图片"):
            return self._text_reply("请发送一张照片, 我来帮你对色 📸")

        # 提取图片 URL
        image_url = self._extract_image_url(payload)
        if not image_url:
            return self._text_reply("无法获取图片, 请重新发送")

        # 下载图片
        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": "SENIA/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                image_bytes = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return self._text_reply("图片下载失败, 请重试")

        # 提取批次号 (从消息文本中)
        lot_id = payload.get("lot_id", "")

        # 处理
        result = process_instant(image_bytes, lot_id=lot_id)

        # 回复
        if self._platform == "dingtalk":
            return result.to_dingtalk_card()
        else:
            return self._text_reply(result.to_text_message())

    def _extract_image_url(self, payload: dict[str, Any]) -> str:
        """从不同平台的消息格式中提取图片 URL."""
        # 企业微信
        if "image" in payload and isinstance(payload["image"], dict):
            return payload["image"].get("url", payload["image"].get("PicUrl", ""))
        # 钉钉
        if "content" in payload and isinstance(payload["content"], dict):
            return payload["content"].get("downloadCode", "")
        # 通用
        return payload.get("PicUrl", payload.get("image_url", ""))

    def _text_reply(self, text: str) -> dict[str, Any]:
        if self._platform == "dingtalk":
            return {"msgtype": "text", "text": {"content": text}}
        return {"msgtype": "text", "text": {"content": text}}

    def async_reply(self, url: str, message: dict[str, Any]) -> None:
        """异步发送回复 (不阻塞主线程)."""
        def _send():
            try:
                data = json.dumps(message, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        Thread(target=_send, daemon=True).start()
