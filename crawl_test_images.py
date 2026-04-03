from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from PIL import Image, UnidentifiedImageError


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_URL = "https://www.bing.com/images/async"
SEARCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bing.com/",
}

MIN_WIDTH = 800
MIN_HEIGHT = 600
MIN_BYTES = 200 * 1024
MAX_BYTES = 5 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 18 * 1024 * 1024
SEARCH_OFFSETS = [0, 35, 70, 105, 140, 175, 210]

ROOT_DIR = Path("test_images")
METADATA_CSV = ROOT_DIR / "metadata.csv"
README_MD = ROOT_DIR / "README.md"


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    prefix: str
    target: int
    queries: tuple[str, ...]
    preferred_source_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    category: str
    query: str
    image_url: str
    source_page: str
    source_domain: str


CATEGORY_CONFIGS: tuple[CategoryConfig, ...] = (
    CategoryConfig(
        key="color_match",
        prefix="color_match",
        target=60,
        queries=(
            "site:alibaba.com decorative film color matching sample",
            "site:alibaba.com PVC film color sample vs production",
            "site:1688.com 装饰膜 对色 样板",
            "site:1688.com 地板膜 印刷 质检",
            "site:made-in-china.com decorative film color matching",
            "wood grain laminate color comparison factory",
            "decorative paper color reference board factory",
        ),
        preferred_source_domains=("alibaba.com", "1688.com", "made-in-china.com", "pinterest.com"),
    ),
    CategoryConfig(
        key="wood_sample",
        prefix="wood_sample",
        target=30,
        queries=(
            "wood grain samples with color codes",
            "wood floor color chart real photo",
            "laminate flooring color options sample board",
            "木纹色卡 地板 色号 实拍",
            "wood color swatch board laminate",
        ),
    ),
    CategoryConfig(
        key="colorchecker",
        prefix="colorchecker",
        target=20,
        queries=(
            "ColorChecker photo calibration wood floor",
            "X-Rite color chart in scene factory",
            "color checker card product photography workshop",
            "色卡 校准 木纹 地板",
        ),
    ),
    CategoryConfig(
        key="factory",
        prefix="factory",
        target=20,
        queries=(
            "decorative film production line factory quality inspection",
            "laminate flooring factory quality control",
            "PVC film printing factory workshop",
            "装饰膜 印刷 车间 质检",
        ),
    ),
    CategoryConfig(
        key="defect",
        prefix="defect",
        target=20,
        queries=(
            "decorative film defect color mismatch",
            "laminate printing defect stripe stain",
            "wood grain film color mismatch sample",
            "装饰膜 色差 不良 条纹 发花",
        ),
    ),
)


def _request_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    retries: int = 5,
    backoff_sec: float = 1.1,
) -> requests.Response | None:
    wait = backoff_sec
    for _ in range(retries):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout, stream=False)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(str(resp.status_code), response=resp)
            resp.raise_for_status()
            return resp
        except Exception:
            time.sleep(wait)
            wait = min(wait * 1.8, 10.0)
    return None


def fetch_candidates_for_query(
    session: requests.Session,
    *,
    category: str,
    query: str,
    offsets: Iterable[int],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for first in offsets:
        resp = _request_with_retries(
            session,
            SEARCH_URL,
            params={
                "q": query,
                "first": first,
                "count": 35,
                "adlt": "off",
            },
            headers=SEARCH_HEADERS,
            timeout=20,
            retries=4,
            backoff_sec=0.9,
        )
        if resp is None:
            continue
        attrs = re.findall(r'm="([^"]+)"', resp.text)
        for attr in attrs:
            try:
                payload = json.loads(html.unescape(attr))
            except Exception:
                continue
            image_url = str(payload.get("murl") or "").strip()
            source_page = str(payload.get("purl") or "").strip()
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            source_domain = urlparse(source_page).netloc.lower()
            candidates.append(
                Candidate(
                    category=category,
                    query=query,
                    image_url=image_url,
                    source_page=source_page,
                    source_domain=source_domain,
                )
            )
        time.sleep(0.25)
    return candidates


def fetch_all_candidates(session: requests.Session, config: CategoryConfig) -> list[Candidate]:
    all_candidates: list[Candidate] = []
    seen: set[str] = set()
    for query in config.queries:
        query_candidates = fetch_candidates_for_query(
            session,
            category=config.key,
            query=query,
            offsets=SEARCH_OFFSETS,
        )
        for cand in query_candidates:
            if cand.image_url in seen:
                continue
            seen.add(cand.image_url)
            all_candidates.append(cand)
    if config.preferred_source_domains:
        preferred = config.preferred_source_domains
        all_candidates.sort(
            key=lambda c: 0
            if any(domain in c.source_domain for domain in preferred)
            else 1
        )
    return all_candidates


def download_and_normalize_image(
    session: requests.Session,
    candidate: Candidate,
) -> tuple[Image.Image, int] | None:
    image_headers = {"User-Agent": USER_AGENT}
    if candidate.source_page:
        parsed = urlparse(candidate.source_page)
        if parsed.scheme and parsed.netloc:
            image_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    resp = _request_with_retries(
        session,
        candidate.image_url,
        headers=image_headers,
        timeout=25,
        retries=3,
        backoff_sec=1.2,
    )
    if resp is None:
        return None
    data = resp.content
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError):
        return None
    if image.mode not in ("RGB",):
        image = image.convert("RGB")
    w, h = image.size
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        return None
    return image, len(data)


def save_jpeg_with_size_limit(image: Image.Image, out_path: Path) -> int | None:
    for quality in (92, 88, 84, 80, 76):
        image.save(out_path, format="JPEG", quality=quality, optimize=True)
        size = out_path.stat().st_size
        if size <= MAX_BYTES:
            if size >= MIN_BYTES:
                return size
            out_path.unlink(missing_ok=True)
            return None
    out_path.unlink(missing_ok=True)
    return None


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    ROOT_DIR.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, str | int]] = []
    seen_hashes: set[str] = set()

    for config in CATEGORY_CONFIGS:
        category_dir = ROOT_DIR / config.key
        category_dir.mkdir(parents=True, exist_ok=True)

        candidates = fetch_all_candidates(session, config)
        saved = 0
        print(f"[{config.key}] candidates={len(candidates)} target={config.target}")

        for cand in candidates:
            if saved >= config.target:
                break
            normalized = download_and_normalize_image(session, cand)
            if normalized is None:
                continue
            image, source_bytes = normalized
            file_name = f"{config.prefix}_{saved + 1:03d}.jpg"
            out_path = category_dir / file_name
            final_bytes = save_jpeg_with_size_limit(image, out_path)
            if final_bytes is None:
                continue
            sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
            if sha256 in seen_hashes:
                out_path.unlink(missing_ok=True)
                continue
            seen_hashes.add(sha256)

            width, height = image.size
            metadata_rows.append(
                {
                    "category": config.key,
                    "file_name": file_name,
                    "path": str(out_path).replace("\\", "/"),
                    "width": width,
                    "height": height,
                    "size_bytes": final_bytes,
                    "source_size_bytes": source_bytes,
                    "query": cand.query,
                    "source_page": cand.source_page,
                    "image_url": cand.image_url,
                    "source_domain": cand.source_domain,
                    "sha256": sha256,
                }
            )
            saved += 1
            if saved % 10 == 0:
                print(f"[{config.key}] saved={saved}/{config.target}")
            time.sleep(0.15)

        print(f"[{config.key}] done saved={saved}/{config.target}")

    with METADATA_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "category",
                "file_name",
                "path",
                "width",
                "height",
                "size_bytes",
                "source_size_bytes",
                "query",
                "source_page",
                "image_url",
                "source_domain",
                "sha256",
            ],
        )
        writer.writeheader()
        writer.writerows(metadata_rows)

    total = len(metadata_rows)
    summary_lines = ["# test_images dataset", "", f"- total_images: {total}", "- format: JPG", ""]
    for cfg in CATEGORY_CONFIGS:
        count = sum(1 for row in metadata_rows if row["category"] == cfg.key)
        summary_lines.append(f"- {cfg.key}: {count}")
    summary_lines.append("")
    summary_lines.append("Source and query details are recorded in metadata.csv.")
    README_MD.write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"ALL_DONE total_saved={total}")
    print(f"METADATA={METADATA_CSV.resolve()}")


if __name__ == "__main__":
    main()
