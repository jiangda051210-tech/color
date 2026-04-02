"""
SENIA 公网部署脚本
================
让系统可以通过互联网访问, 不限局域网.

三种方式:
  1. ngrok (推荐, 最简单)
  2. cloudflare tunnel (免费, 无需注册)
  3. 直接部署到云服务器 (VPS)

用法:
  python deploy_public.py              # 默认 ngrok
  python deploy_public.py --method cf  # cloudflare tunnel
  python deploy_public.py --port 8877  # 指定端口
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def check_requirements():
    """检查必要依赖."""
    print("检查依赖...")
    deps = {"cv2": "opencv-python", "numpy": "numpy", "fastapi": "fastapi",
            "pydantic": "pydantic", "uvicorn": "uvicorn"}
    missing = []
    for mod, pkg in deps.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print(f"安装: pip install {' '.join(missing)}")
        return False
    print("  ✅ 所有依赖就绪")
    return True


def start_server(port: int = 8877) -> subprocess.Popen:
    """启动 FastAPI 服务."""
    print(f"\n启动 SENIA 服务 (端口 {port})...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "elite_api:app",
         "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(Path(__file__).parent),
    )
    time.sleep(3)
    if proc.poll() is not None:
        print("  ❌ 服务启动失败")
        sys.exit(1)
    print(f"  ✅ 服务运行中: http://localhost:{port}")
    return proc


def setup_ngrok(port: int = 8877):
    """用 ngrok 创建公网隧道."""
    print("\n=== ngrok 公网隧道 ===")
    print("检查 ngrok...")

    # 检查 ngrok 是否安装
    try:
        result = subprocess.run(["ngrok", "version"], capture_output=True, text=True)
        print(f"  ✅ {result.stdout.strip()}")
    except FileNotFoundError:
        print("  ❌ ngrok 未安装")
        print("")
        print("  安装方法:")
        print("    1. 访问 https://ngrok.com/download")
        print("    2. 下载并安装 (Windows/Mac/Linux)")
        print("    3. 注册免费账号, 获取 authtoken")
        print("    4. 运行: ngrok config add-authtoken <your-token>")
        print("    5. 重新运行本脚本")
        return None

    print(f"\n开启 ngrok 隧道 → localhost:{port}")
    proc = subprocess.Popen(
        ["ngrok", "http", str(port), "--log=stdout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)

    # 获取公网 URL
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5)
        data = json.loads(resp.read())
        tunnels = data.get("tunnels", [])
        for t in tunnels:
            url = t.get("public_url", "")
            if url.startswith("https://"):
                return url
    except Exception:
        pass

    return None


def setup_cloudflare(port: int = 8877):
    """用 Cloudflare Tunnel 创建公网隧道 (免费)."""
    print("\n=== Cloudflare Tunnel ===")
    try:
        result = subprocess.run(["cloudflared", "version"], capture_output=True, text=True)
        print(f"  ✅ {result.stdout.strip()}")
    except FileNotFoundError:
        print("  ❌ cloudflared 未安装")
        print("  安装: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/")
        return None

    print(f"\n开启 Cloudflare Tunnel → localhost:{port}")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(5)

    # cloudflared 会在 stderr 输出 URL
    output = proc.stderr.read(4096).decode("utf-8", errors="replace")
    for line in output.split("\n"):
        if "trycloudflare.com" in line or "cfargotunnel.com" in line:
            url = line.split("http")[1] if "http" in line else ""
            if url:
                return "https" + url.split()[0]

    return None


def print_access_info(url: str | None, port: int):
    """打印访问信息."""
    print("\n" + "=" * 60)
    print("  SENIA 智能对色系统 — 已启动")
    print("=" * 60)
    print(f"\n  🏠 本地访问:    http://localhost:{port}")
    if url:
        print(f"  🌐 公网访问:    {url}")
        print(f"  📱 手机扫码:    (用手机浏览器打开上面的公网链接)")
    else:
        print(f"  ⚠️  公网隧道未启动 (仅局域网可用)")
        print(f"  💡 局域网访问:  http://<你的IP>:{port}")
    print(f"\n  📊 API文档:     http://localhost:{port}/docs")
    print(f"  📋 全功能面板:  http://localhost:{port}/v1/web/dashboard")
    print(f"\n  按 Ctrl+C 停止服务")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="SENIA 公网部署")
    parser.add_argument("--port", type=int, default=8877, help="服务端口")
    parser.add_argument("--method", choices=["ngrok", "cf", "local"], default="local",
                        help="部署方式: ngrok/cf(cloudflare)/local")
    parser.add_argument("--no-server", action="store_true", help="不启动服务 (仅启动隧道)")
    args = parser.parse_args()

    if not check_requirements():
        sys.exit(1)

    server_proc = None
    if not args.no_server:
        server_proc = start_server(args.port)

    url = None
    if args.method == "ngrok":
        url = setup_ngrok(args.port)
    elif args.method == "cf":
        url = setup_cloudflare(args.port)

    print_access_info(url, args.port)

    try:
        if server_proc:
            server_proc.wait()
    except KeyboardInterrupt:
        print("\n停止服务...")
        if server_proc:
            server_proc.terminate()


if __name__ == "__main__":
    main()
