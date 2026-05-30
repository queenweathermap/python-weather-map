# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# JMA Guidance:
#   HTML → スクショ → JPG → R2一時保存 → Notion取り込み → Discord
#
# 方針:
#   ・Notion = 正本
#   ・R2 = 21日保存の一時置き場
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


from module.utils.r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    append_images,
    append_imported_images_from_urls,
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

VIEWPORT_WIDTH = int(os.environ.get("GUIDANCE_VIEWPORT_WIDTH", "1200"))
VIEWPORT_HEIGHT = int(os.environ.get("GUIDANCE_VIEWPORT_HEIGHT", "900"))
WAIT_MS = int(os.environ.get("GUIDANCE_WAIT_MS", "2500"))

NOTION_IMPORT_IMAGES = os.environ.get("NOTION_IMPORT_IMAGES", "0").lower() in ("1", "true", "yes", "on")
NOTION_IMPORT_TIMEOUT_SECONDS = int(os.environ.get("NOTION_IMPORT_TIMEOUT_SECONDS", "180"))
NOTION_IMPORT_POLL_SECONDS = float(os.environ.get("NOTION_IMPORT_POLL_SECONDS", "2.0"))

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


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# スクショ
# =============================================================================

def capture():
    atts = []
    errors = []

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    user = os.getenv("JMA_ADV_USER", "").strip()
    password = os.getenv("JMA_ADV_PASS", "").strip()

    if not user or not password:
        errors.append("JMA guidance auth env is missing: JMA_ADV_USER / JMA_ADV_PASS")
        return atts, errors

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context_kwargs = {
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        }

        if user and password:
            context_kwargs["http_credentials"] = {
                "username": user,
                "password": password,
            }

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        for name, label, url in GUIDANCE_TARGETS:
            try:
                print(f"[INFO] {label}")
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(WAIT_MS)

                body_text = page.locator("body").inner_text(timeout=5000)
                if "Authentication Failed" in body_text:
                    errors.append(f"{label}: authentication failed")
                    continue

                png = page.screenshot(full_page=True)
                jpg = png_to_jpg(png)

                fname = f"{name}.jpg"
                atts.append((fname, jpg, "image/jpeg"))

            except Exception as e:
                errors.append(f"{label}: {e}")

        context.close()
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

def write_notion(base_jst, prefix, urls, rep, errors, atts):
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

        if urls:
            if NOTION_IMPORT_IMAGES:
                items = []
                for idx, url in enumerate(urls):
                    if idx < len(atts):
                        fname, _blob, mime = atts[idx]
                    else:
                        fname, mime = f"guidance_{idx + 1:02d}.jpg", "image/jpeg"
                    items.append((fname, url, mime or "image/jpeg"))

                append_imported_images_from_urls(
                    page_id,
                    items,
                    chunk=10,
                    timeout_seconds=NOTION_IMPORT_TIMEOUT_SECONDS,
                    poll_seconds=NOTION_IMPORT_POLL_SECONDS,
                )
            else:
                append_images(page_id, urls)

    except Exception as e:
        print(f"[WARN] Notion image import/append failed: {e}")

        # 移行中の安全策: Notion取り込みに失敗した場合は従来の外部URL埋め込みへ戻す
        try:
            if urls:
                append_images(page_id, urls)
        except Exception as e2:
            print(f"[WARN] Notion fallback append_images failed: {e2}")

    try:
        append_heading(page_id, "ガイダンス入口", level=2)
        append_bookmark(
            page_id,
            "https://www.jma.go.jp/bosai/advisor/",
            caption="気象庁 ガイダンス"
        )
    except Exception as e:
        print(f"[WARN] Notion bookmark failed: {e}")

    return page_id

# =============================================================================
# Discord
# =============================================================================

def post_discord(urls, errors, notion_url=""):
    if not discord_url():
        return

    # 画像
    if urls:
        post_discord_item_image_urls(
            webhook_url=discord_url(),
            title="📊 ガイダンス",
            image_urls=urls,
            notion_url="",
            rjtd="",
            init_jst="",
        )

    # Notionページ
    if notion_url:
        try:
            requests.post(
                discord_url(),
                json={
                    "content": f"📘 Notionページ\n{notion_url}"
                },
                timeout=10,
            )
        except Exception as e:
            print(e)

    # ポータル（テキスト）
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
        notion_url=notion_url,
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

    page_id = write_notion(base_jst, prefix, urls, rep, errors, atts)
    notion_url = notion_page_url(page_id) if page_id else ""

    if notion_url:
        print(f"[OK] Notion URL: {notion_url}")

    post_discord(urls, errors, notion_url=notion_url)

    print("=== Done ===")

if __name__ == "__main__":
    main()
