"""
SENIA 拍摄工位规格 + iPhone 拍摄控制 + ArUco 标记生成
=====================================================
把硬件要求变成可检查的软件规格, 并提供落地工具.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════
# 拍摄工位 BOM (物料清单) + 搭建指南
# ══════════════════════════════════════════════════════════

CAPTURE_STATION_BOM: list[dict[str, Any]] = [
    {
        "item": "D65 LED灯箱",
        "spec": "色温6500K±200K, 显色指数Ra≥95, 功率≥20W",
        "purpose": "标准光源, 消除色温漂移",
        "price_range": "800~2000元",
        "where_to_buy": "淘宝搜'D65标准光源箱'或'印刷看色台'",
        "alternatives": [
            "如暂时买不到D65灯箱, 可用两盏6500K Ra95+ LED面板灯, 45°对称布光",
            "品牌推荐: 天友利 T60(5), 三恩驰 CC120, 或 X-Rite SpectraLight",
        ],
        "critical": True,
    },
    {
        "item": "翻拍架/手机支架",
        "spec": "可固定iPhone在40cm高度, 镜头正对下方",
        "purpose": "消除透视畸变, 保证拍摄一致性",
        "price_range": "100~500元",
        "where_to_buy": "淘宝搜'翻拍架'或'俯拍支架'",
        "alternatives": [
            "DIY方案: 铝型材搭L形支架, 用手机夹固定",
            "简易方案: 桌面悬臂手机支架 (能锁定高度和角度即可)",
        ],
        "critical": True,
    },
    {
        "item": "N7中性灰背景板",
        "spec": "Munsell N7 (L*≈70), 哑光表面, 尺寸≥60×80cm",
        "purpose": "统一背景, 避免地面/桌面颜色干扰检测",
        "price_range": "50~200元",
        "where_to_buy": "淘宝搜'18%灰卡 A2'或'中性灰背景板'",
        "alternatives": [
            "临时方案: 用灰色无纺布铺底 (不是白色!)",
            "DIY: 灰色亚克力板或灰色PVC软板",
        ],
        "critical": True,
    },
    {
        "item": "X-Rite ColorChecker Classic Mini",
        "spec": "24色标准色卡, 尺寸约 8.25×5.7cm",
        "purpose": "色彩校正基准, 补偿光源和设备差异",
        "price_range": "300~800元",
        "where_to_buy": "淘宝搜'ColorChecker Mini'或'爱色丽色卡'",
        "alternatives": [
            "平替方案: SpyderCHECKR 24色卡 (~300元)",
            "最低要求: 至少一张18%灰卡 (用于白平衡校正)",
        ],
        "critical": False,  # 没有也能用, 但精度降一档
    },
    {
        "item": "ArUco定位标记",
        "spec": "4个DICT_4X4_50标记, 打印在白色纸上, 贴在拍摄台四角",
        "purpose": "自动定位和透视校正",
        "price_range": "几乎免费 (自己打印)",
        "where_to_buy": "用本模块的 generate_aruco_markers() 生成后打印",
        "alternatives": [
            "简易方案: 不贴标记, 系统自动用轮廓检测 (精度略低)",
        ],
        "critical": False,
    },
    {
        "item": "iPhone 12 Pro 或更高",
        "spec": "支持 ProRAW (DNG) 格式拍摄",
        "purpose": "绕开iOS计算摄影管线, 获取线性色彩数据",
        "price_range": "已有设备",
        "where_to_buy": "-",
        "alternatives": [
            "最低要求: iPhone 11+ (用JPEG但关闭HDR/Deep Fusion)",
            "安卓方案: 支持RAW/DNG拍摄的手机 + Open Camera App",
        ],
        "critical": True,
    },
]


# ══════════════════════════════════════════════════════════
# 搭建步骤
# ══════════════════════════════════════════════════════════

BUILD_STEPS: list[dict[str, str]] = [
    {
        "step": "1. 选定位置",
        "detail": "选一个远离窗户的角落, 避免自然光干扰. 桌面高度80~90cm. "
                  "如果无法避开窗户, 用遮光布挡住.",
    },
    {
        "step": "2. 铺设背景板",
        "detail": "将N7灰色背景板平铺在桌面上, 确保覆盖拍摄区域 (至少60×80cm). "
                  "背景板要平整无褶皱.",
    },
    {
        "step": "3. 安装灯箱/灯具",
        "detail": "D65灯箱放在桌面上方, 光源以45°角照射拍摄区域. "
                  "如果用两盏LED面板灯, 左右各一盏, 对称45°布光. "
                  "灯到桌面距离约50~60cm.",
    },
    {
        "step": "4. 安装翻拍架",
        "detail": "将翻拍架/手机支架装好, 手机镜头距桌面约40cm, "
                  "镜头正对下方 (0°角). 用水平仪检查是否水平.",
    },
    {
        "step": "5. 贴ArUco标记 (可选)",
        "detail": "打印4个ArUco标记 (用 generate_aruco_markers() 生成), "
                  "分别贴在拍摄区域的四角, 间距约50×35cm.",
    },
    {
        "step": "6. iPhone设置",
        "detail": "设置 → 相机 → 格式 → Apple ProRAW 开启. "
                  "拍摄时: 关闭闪光灯, 关闭HDR, 关闭Live Photo. "
                  "长按对焦锁定 (AE/AF Lock), 手动拖动曝光滑块微调.",
    },
    {
        "step": "7. 放置样品",
        "detail": "大货平铺在背景板上, 标样放在大货右上角. "
                  "★ 标样不要叠在大货上面! 要并排或留1cm间隙. "
                  "色卡放在大货左下角 (如果有).",
    },
    {
        "step": "8. 验证拍摄",
        "detail": "拍一张测试照, 用 senia_image_pipeline.py 分析. "
                  "检查: 大货/标样是否都被检测到, 置信度是否>0.8. "
                  "如果检测不到, 调整灯光或位置.",
    },
]


# ══════════════════════════════════════════════════════════
# iPhone 拍摄 App 控制参数
# ══════════════════════════════════════════════════════════

IPHONE_CAMERA_SETTINGS = {
    "format": {
        "preferred": "Apple ProRAW (DNG)",
        "fallback": "HEIF 或 JPEG (关闭所有计算摄影)",
        "settings_path": "设置 → 相机 → 格式 → Apple ProRAW",
    },
    "disable_features": [
        "Smart HDR → 关闭 (设置→相机→Smart HDR 关)",
        "Deep Fusion → 无法单独关闭, ProRAW模式自动绕过",
        "Night Mode → 关闭 (拍摄界面左上角月亮图标)",
        "Live Photo → 关闭",
        "Flash → 关闭",
        "Macro → 关闭 (iPhone 13 Pro+ 在近距离会自动切超广角)",
    ],
    "lock_exposure": {
        "method": "长按画面中灰色区域 → 出现'AE/AF锁定' → 上下滑动微调曝光",
        "target": "灰卡/背景板呈现为中灰色, 不过曝不过暗",
    },
    "lock_white_balance": {
        "method_proraw": "ProRAW模式下WB存储在DNG元数据中, 后处理时统一校正",
        "method_jpeg": "使用第三方App (Halide/ProCamera) 手动锁定WB为6500K",
    },
    "focus": {
        "method": "长按画面中膜表面 → AE/AF锁定 → 不要再触摸屏幕",
        "distance": "40cm (翻拍架固定后, 焦距自动一致)",
    },
    "third_party_apps": {
        "recommended": [
            "Halide Mark II — 完全手动控制, 支持ProRAW, 可锁定WB/ISO/快门",
            "ProCamera — 手动WB/曝光/对焦, 支持DNG",
        ],
        "free_alternative": "iOS原生相机 + ProRAW即可, 第三方App非必须",
    },
}


# ══════════════════════════════════════════════════════════
# ArUco 标记生成
# ══════════════════════════════════════════════════════════

def generate_aruco_markers(
    output_dir: Path,
    marker_ids: list[int] | None = None,
    marker_size_px: int = 200,
    dict_name: str = "DICT_4X4_50",
) -> list[Path]:
    """
    生成 ArUco 定位标记图片, 打印后贴在拍摄台四角.

    返回生成的图片路径列表.
    """
    try:
        import cv2
    except ImportError:
        raise RuntimeError("需要 OpenCV: pip install opencv-python")

    if not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV 版本不支持 aruco 模块")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if marker_ids is None:
        marker_ids = [0, 1, 2, 3]

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    paths: list[Path] = []

    for mid in marker_ids:
        img = cv2.aruco.generateImageMarker(dictionary, mid, marker_size_px)
        # 加白色边框 (打印时保留)
        bordered = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
        path = output_dir / f"aruco_marker_{mid}.png"
        cv2.imwrite(str(path), bordered)
        paths.append(path)

    # 生成一张 A4 拼版 (4个标记在一张纸上)
    a4_w, a4_h = 2480, 3508  # 300dpi A4
    a4 = 255 * np.ones((a4_h, a4_w), dtype=np.uint8)
    sz = bordered.shape[0]
    margin = 100
    positions = [
        (margin, margin),  # 左上
        (a4_w - sz - margin, margin),  # 右上
        (margin, a4_h - sz - margin),  # 左下
        (a4_w - sz - margin, a4_h - sz - margin),  # 右下
    ]

    import numpy as np
    for i, (x, y) in enumerate(positions):
        if i < len(marker_ids):
            marker_img = cv2.aruco.generateImageMarker(dictionary, marker_ids[i], marker_size_px)
            marker_bordered = cv2.copyMakeBorder(marker_img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
            h, w = marker_bordered.shape[:2]
            a4[y:y + h, x:x + w] = marker_bordered

    a4_path = output_dir / "aruco_a4_print.png"
    cv2.imwrite(str(a4_path), a4)
    paths.append(a4_path)

    return paths


# ══════════════════════════════════════════════════════════
# 导出: 工位搭建报告 (给老板/采购看)
# ══════════════════════════════════════════════════════════

def export_station_guide(output_path: Path) -> Path:
    """导出拍摄工位搭建指南为 JSON."""
    guide = {
        "title": "SENIA 对色拍摄工位搭建指南",
        "total_budget": "约 2000~3500 元",
        "bom": CAPTURE_STATION_BOM,
        "build_steps": BUILD_STEPS,
        "iphone_settings": IPHONE_CAMERA_SETTINGS,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(guide, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def print_station_guide() -> None:
    """终端打印搭建指南."""
    print("=" * 60)
    print("  SENIA 对色拍摄工位搭建指南")
    print("  预算: 约 2000~3500 元")
    print("=" * 60)

    print("\n【物料清单】")
    total_min = 0
    total_max = 0
    for item in CAPTURE_STATION_BOM:
        critical = " ★必须" if item["critical"] else " (可选)"
        print(f"\n  {item['item']}{critical}")
        print(f"    规格: {item['spec']}")
        print(f"    用途: {item['purpose']}")
        print(f"    价格: {item['price_range']}")
        print(f"    购买: {item['where_to_buy']}")
        if item.get("alternatives"):
            for alt in item["alternatives"]:
                print(f"    替代: {alt}")

    print("\n" + "=" * 60)
    print("【搭建步骤】")
    for step in BUILD_STEPS:
        print(f"\n  {step['step']}")
        print(f"    {step['detail']}")

    print("\n" + "=" * 60)
    print("【iPhone 设置】")
    for key, value in IPHONE_CAMERA_SETTINGS.items():
        if isinstance(value, dict):
            print(f"\n  {key}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        elif isinstance(value, list):
            print(f"\n  {key}:")
            for v in value:
                print(f"    - {v}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    if "--generate-aruco" in sys.argv:
        import numpy as np
        paths = generate_aruco_markers(Path("./aruco_markers"))
        print("ArUco 标记已生成:")
        for p in paths:
            print(f"  {p}")
    elif "--export" in sys.argv:
        path = export_station_guide(Path("./capture_station_guide.json"))
        print(f"指南已导出: {path}")
    else:
        print_station_guide()
