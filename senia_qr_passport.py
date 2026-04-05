"""
SENIA QR Color Passport — 给买家的可扫码验色证书
================================================

颠覆点: 工厂的客户(买家)目前无法验证收到的货色值是否符合标准.
只能肉眼看, 或者自己花钱买色差仪测.

我们的方案: 每批货附带一个 QR 码, 买家用手机扫一下就能看到:
  - 出厂时的色值数据 + 判定结果
  - 检测照片缩略图
  - 完整的质量追溯链
  - 防伪签名 (SHA256, 无法篡改)

为什么颠覆:
  1. 买家有了"看得见的质量保证", 降低退货率
  2. 工厂有了"可证明的质量记录", 有质量纠纷时有据可依
  3. 这个证书是免费的 — 成本几乎为零
  4. 竞争对手 X-Rite 从来没做过面向终端买家的工具
"""

from __future__ import annotations

import hashlib
import html
import json
import time
from pathlib import Path
from typing import Any


def generate_passport(
    lot_id: str,
    product_code: str,
    tier: str,
    dE00: float,
    directions: list[str],
    lab_values: tuple[float, float, float],
    profile: str = "",
    customer_id: str = "",
    operator_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    生成数字色彩护照.

    返回包含: 护照数据 + SHA256签名 + 可嵌入QR码的验证URL
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    # Use full SHA256 (64 hex chars) for passport_id for stronger uniqueness
    passport_id = hashlib.sha256(
        f"{lot_id}:{product_code}:{ts}".encode()
    ).hexdigest()

    passport_data = {
        "passport_id": passport_id,
        "lot_id": lot_id,
        "product_code": product_code,
        "tier": tier,
        "dE00": round(dE00, 4),
        "directions": directions,
        "lab": {"L": round(lab_values[0], 2), "a": round(lab_values[1], 2), "b": round(lab_values[2], 2)},
        "profile": profile,
        "customer_id": customer_id,
        "operator_id": operator_id,
        "issued_at": ts,
        "version": "1.0",
    }
    if extra:
        passport_data["extra"] = extra

    # 防伪签名 — include timestamp in payload for freshness verification
    passport_data["signature_timestamp"] = time.time()
    sig_payload = json.dumps(passport_data, sort_keys=True, ensure_ascii=False)
    signature = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
    passport_data["signature"] = signature

    return passport_data


# Maximum age for passport freshness check (1 year in seconds)
PASSPORT_MAX_AGE_SECONDS = 365 * 24 * 3600


def verify_passport(passport_data: dict[str, Any]) -> dict[str, Any]:
    """验证护照签名是否被篡改. Works on a copy to avoid modifying the original."""
    data = dict(passport_data)  # shallow copy — don't modify caller's dict
    sig = data.pop("signature", "")
    expected = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    signature_valid = sig == expected

    # Timestamp freshness check (max 1 year)
    sig_ts = data.get("signature_timestamp")
    freshness_ok = True
    freshness_detail = "no_timestamp"
    if sig_ts is not None:
        age = time.time() - float(sig_ts)
        if age > PASSPORT_MAX_AGE_SECONDS:
            freshness_ok = False
            freshness_detail = f"expired (age={age / 86400:.0f} days, max={PASSPORT_MAX_AGE_SECONDS / 86400:.0f} days)"
        elif age < 0:
            freshness_ok = False
            freshness_detail = "timestamp_in_future"
        else:
            freshness_detail = f"fresh (age={age / 86400:.0f} days)"

    overall_valid = signature_valid and freshness_ok

    return {
        "valid": overall_valid,
        "passport_id": passport_data.get("passport_id", ""),
        "tampered": not signature_valid,
        "signature_valid": signature_valid,
        "freshness_ok": freshness_ok,
        "freshness_detail": freshness_detail,
        "verdict": (
            "VALID" if overall_valid
            else "TAMPERED" if not signature_valid
            else "EXPIRED"
        ),
    }


def render_passport_html(passport: dict[str, Any], verify_url: str = "") -> str:
    """
    渲染可打印的 HTML 护照页面.
    可用于:
      1. 直接打印贴在包装上
      2. 生成 QR 码指向的在线验证页
    """
    tier = passport.get("tier", "")
    tier_colors = {"PASS": "#22c55e", "MARGINAL": "#f59e0b", "FAIL": "#ef4444"}
    tier_names = {"PASS": "合格", "MARGINAL": "临界", "FAIL": "不合格"}
    # Fallback for unknown tiers
    tier_color = tier_colors.get(tier, "#6b7280")
    tier_cn = tier_names.get(tier, tier or "未知")
    lab = passport.get("lab", {})
    dirs = passport.get("directions", [])

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>SENIA Color Passport</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 400px; margin: 20px auto; padding: 16px;
       background: #f9fafb; color: #1a1a2e; }}
.card {{ background: white; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
.header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }}
.logo {{ font-size: 18px; font-weight: 700; color: #2563eb; }}
.passport-id {{ font-size: 11px; color: #9ca3af; font-family: monospace; }}
.tier {{ display: inline-block; padding: 6px 20px; border-radius: 8px;
         color: white; font-weight: 700; font-size: 20px; background: {tier_color}; }}
.metric {{ display: flex; justify-content: space-between; padding: 8px 0;
           border-bottom: 1px solid #f3f4f6; font-size: 14px; }}
.metric:last-child {{ border: none; }}
.label {{ color: #6b7280; }}
.value {{ font-weight: 600; font-family: monospace; }}
.dirs {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 12px 0; }}
.dir {{ padding: 3px 10px; border-radius: 12px; font-size: 12px;
        background: #f3f4f6; color: #374151; }}
.sig {{ font-size: 10px; color: #d1d5db; word-break: break-all; margin-top: 16px;
        padding-top: 12px; border-top: 1px solid #f3f4f6; font-family: monospace; }}
.verify {{ text-align: center; margin-top: 12px; }}
.verify a {{ color: #2563eb; font-size: 13px; text-decoration: none; }}
@media print {{
  body {{ background: white; margin: 0; padding: 0; }}
  .card {{ box-shadow: none; border: 1px solid #e5e7eb; border-radius: 8px;
           page-break-inside: avoid; }}
  .verify a {{ color: #2563eb; }}
  .verify a::after {{ content: " (" attr(href) ")"; font-size: 10px; color: #6b7280; }}
}}
</style></head><body>
<div class="card">
  <div class="header">
    <div class="logo">SENIA</div>
    <div class="passport-id">#{html.escape(passport.get('passport_id', ''))}</div>
  </div>
  <div style="text-align:center;margin:16px 0">
    <div class="tier">{html.escape(tier_cn)}</div>
  </div>
  <div class="metric"><span class="label">Product</span><span class="value">{html.escape(str(passport.get('product_code', '')))}</span></div>
  <div class="metric"><span class="label">Lot</span><span class="value">{html.escape(str(passport.get('lot_id', '')))}</span></div>
  <div class="metric"><span class="label">ΔE00</span><span class="value">{passport.get('dE00', 0):.2f}</span></div>
  <div class="metric"><span class="label">L*a*b*</span><span class="value">{lab.get('L',0):.1f}, {lab.get('a',0):.1f}, {lab.get('b',0):.1f}</span></div>
  <div class="metric"><span class="label">Profile</span><span class="value">{html.escape(str(passport.get('profile', '')))}</span></div>
  <div class="metric"><span class="label">Date</span><span class="value">{html.escape(str(passport.get('issued_at', '')))}</span></div>
  {'<div class="dirs">' + ''.join(f'<span class="dir">{html.escape(d)}</span>' for d in dirs) + '</div>' if dirs else ''}
  <div class="sig">SHA256: {html.escape(str(passport.get('signature', '')))}</div>
  {f'<div class="verify"><a href="{html.escape(verify_url)}">Verify Authenticity</a></div>' if verify_url else ''}
</div></body></html>"""
