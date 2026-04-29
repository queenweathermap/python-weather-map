# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# JMA Guidance:
#   HTML → スクショ → JPG → R2 → Notion → Discord
#
# 方針:
#   ・Notion = 正本
#   ・Discord = ビュー
#   ・ポータルリンクはテキスト投稿
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import sys
import time
import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Optional

from PIL import Image
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    append_images,
    append_heading,
    append_bookmark,
)
from module.utils.discord_utils import (
    post_discord_item_image_urls,
    post_discord_complete,
)

# =============================================================================
# 設定
# =============================================================================

OUTPUT_DIR = "/tmp/jma_guidance"

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "90"))
R2_ENABLE = os.environ.get("R2_ENABLE", "1") in ("1", "true", "yes")
R2_PREFIX = os.environ.get("R2_PREFIX", "guidance")

VIEWPORT_WIDTH = 1200
VIEWPORT_HEIGHT = 900
WAIT_MS = 2500

Attachment = Tuple[str, bytes, str]

GUIDANCE_TARGETS = [
    ("guid_precip_table", "降水一覧", "https://www.jma.go.jp/bosai/advisor/guid_table.html"),
    ("guid_precip_map", "降水分布", "https://www.jma.go.jp/bosai/advisor/guid_map.html"),
    ("guid_wind", "風", "https://www.jma.go.jp/bosai/advisor/guid_table_wind.html"),
    ("guid_cold", "寒気", "https://www.jma.go.jp/bosai/advisor/cold_table.html"),
    ("guid_landslide", "土砂", "https://www.jma.go.jp/bosai/advisor/gpv.html"),
]

# =============================================================================
# Utility
# =============================================================================

def jst_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))

def png_to_jpg(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=JPEG_QUALITY)
    return out.getvalue()

def discord_url():
    return os.getenv("DISCORD_GUIDANCE_WEBHOOK_URL", "")

# =============================================================================
# スクショ
# =============================================================================

def capture():
    atts = []
    errors = []

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})

        for name, label, url in GUIDANCE_TARGETS:
            try:
                print(f"[INFO] {label}")
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(WAIT_MS)

                png = page.screenshot(full_page=True)
                jpg = png_to_jpg(png)

                fname = f"{name}.jpg"
                atts.append((fname, jpg, "image/jpeg"))

            except Exception as e:
                errors.append(f"{label}: {e}")

        browser.close()

    return atts, errors

# =============================================================================
# R2
# =============================================================================

def upload(prefix, atts):
    urls = []
    rep = None

    if not R2_ENABLE:
        return urls, rep

    for fname, blob, mime in atts:
        key = f"{prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)

        urls.append(url)
        if rep is None:
            rep = url

    return urls, rep

# =============================================================================
# Notion
# =============================================================================

def write_notion(base_jst, prefix, urls, rep, errors):
    if not notion_enabled():
        return None

    title = f"Guidance / {base_jst.strftime('%Y%m%d %H:%M')}"

    page_id = create_db_row(
        title=title,
        category="Guidance",
        init_jst_iso=base_jst.isoformat(),
        memo="\n".join(errors),
        rjtd="",
        prefix=prefix,
        r2_url=rep or "",
        autogen=True,
        icon_emoji="📊",
    )

    if not page_id:
        return None

    time.sleep(1)

    try:
        append_heading(page_id, "ガイダンス画像", level=2)
        append_images(page_id, urls)
    except:
        pass

    try:
        append_heading(page_id, "ガイダンス入口", level=2)
        append_bookmark(
            page_id,
            "https://www.jma.go.jp/bosai/advisor/",
            caption="気象庁 ガイダンス"
        )
    except:
        pass

    return page_id

# =============================================================================
# Discord
# =============================================================================

def post_discord(urls, errors):
    if not discord_url():
        return

    # 画像
    post_discord_item_image_urls(
        webhook_url=discord_url(),
        title="📊 ガイダンス",
        image_urls=urls,
        notion_url="",
        rjtd="",
        init_jst="",
    )

    # ★ ポータル（テキスト）
    try:
        requests.post(
            discord_url(),
            json={
                "content": "🔗 ガイダンス入口\nhttps://www.jma.go.jp/bosai/advisor/"
            },
            timeout=10,
        )
    except Exception as e:
        print(e)

    # 完了
    post_discord_complete(
        webhook_url=discord_url(),
        category="Guidance",
        notion_url="",
        attach_count=len(urls),
        errors=errors,
    )

# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Guidance ===")

    base_jst = jst_now()
    prefix = f"{R2_PREFIX}/{base_jst.strftime('%Y%m%d_%H%M')}"

    atts, errors = capture()
    urls, rep = upload(prefix, atts)
    write_notion(base_jst, prefix, urls, rep, errors)
    post_discord(urls, errors)

    print("=== Done ===")

if __name__ == "__main__":
    main()
