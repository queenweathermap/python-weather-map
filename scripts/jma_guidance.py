# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_guidance.py
#
# JMA Guidance:
#   気象庁ガイダンスHTML → スクリーンショットPNG → JPG → R2 → Notion DB → Discord
#
# 対象:
#   - 最大降水量・降雪量ガイダンス一覧表
#   - 最大降水量・降雪量ガイダンス地図表示
#   - 最大風速ガイダンス一覧表
#   - 寒気概要
#
# 設計:
#   - Notion / R2 が正本
#   - Discord は画像ビューア
#   - Notionは1DBのまま、区分 = Guidance
#   - Discordは guidance チャンネルへ投稿
#
# 必要:
#   pip install playwright pillow requests boto3 notion-client
#   playwright install chromium
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import sys
import time
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


DATA_DIR = "/tmp/jma_guidance_data"
OUTPUT_DIR = "/tmp/jma_guidance"

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "90"))
R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "guidance").strip().strip("/")

VIEWPORT_WIDTH = int(os.environ.get("GUIDANCE_VIEWPORT_WIDTH", "1200"))
VIEWPORT_HEIGHT = int(os.environ.get("GUIDANCE_VIEWPORT_HEIGHT", "900"))
WAIT_MS = int(os.environ.get("GUIDANCE_WAIT_MS", "2500"))

Attachment = Tuple[str, bytes, str]


# =============================================================================
# Guidance targets
# =============================================================================
GUIDANCE_TARGETS = [
    (
        "guid_precip_table",
        "最大降水量・降雪量ガイダンス一覧表",
        "https://www.jma.go.jp/bosai/advisor/guid_table.html",
    ),
    (
        "guid_precip_map",
        "最大降水量・降雪量ガイダンス地図表示",
        "https://www.jma.go.jp/bosai/advisor/guid_map.html",
    ),
    (
        "guid_wind_table",
        "最大風速ガイダンス一覧表",
        "https://www.jma.go.jp/bosai/advisor/guid_table_wind.html",
    ),
    (
        "guid_cold_table",
        "寒気概要",
        "https://www.jma.go.jp/bosai/advisor/cold_table.html",
    ),
]


# =============================================================================
# Env / time helpers
# =============================================================================
def env_bool(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(jst_tz())


def floor_to_guidance_base_jst(dt_jst: datetime) -> datetime:
    """
    Notionの発行基準時刻用。

    ガイダンスページは「最新」状態を見る運用なので、
    03/09/15/21 JST の6時間境界に丸める。
    """
    dt_shift = dt_jst - timedelta(hours=3)
    h = (dt_shift.hour // 6) * 6
    dt_floor = dt_shift.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(hours=3)
    return dt_floor


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# Discord
# =============================================================================
def discord_guidance_webhook_url() -> str:
    """
    Guidance専用DiscordチャンネルのWebhook URL。

    優先:
      DISCORD_GUIDANCE_WEBHOOK_URL

    互換:
      DISCORD_WEBHOOK_URL
    """
    return (
        os.getenv("DISCORD_GUIDANCE_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    )


def discord_guidance_enabled() -> bool:
    return env_bool("DISCORD_ENABLE", "0") and bool(discord_guidance_webhook_url())


# =============================================================================
# Image conversion
# =============================================================================
def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 90) -> bytes:
    """
    PlaywrightのスクリーンショットPNGをJPG化する。
    R2/Notion/DiscordではJPGの方が安定する。
    """
    with Image.open(io.BytesIO(png_bytes)) as im:
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


# =============================================================================
# Screenshot
# =============================================================================
def capture_guidance_pages() -> Tuple[List[Attachment], List[str]]:
    """
    GuidanceページをPlaywrightで開き、スクリーンショットを撮る。

    returns:
      attachments:
        R2へアップロードするJPG画像

      errors:
        取得エラー一覧
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    atts: List[Attachment] = []
    errors: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={
                "width": VIEWPORT_WIDTH,
                "height": VIEWPORT_HEIGHT,
            },
            device_scale_factor=1,
        )

        for base_name, label, url in GUIDANCE_TARGETS:
            try:
                print(f"[INFO] capture: {label} {url}")

                page.goto(url, wait_until="networkidle", timeout=60000)

                # JavaScript描画・表の反映待ち
                page.wait_for_timeout(WAIT_MS)

                # ページ全体ではなく、見えている範囲を優先。
                # ガイダンス表は横長なので、viewportを固定して撮る方が読みやすい。
                png = page.screenshot(full_page=True)

                jpg = png_bytes_to_jpg_bytes(png, quality=JPEG_QUALITY)

                fname = f"{base_name}.jpg"

                try:
                    with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                        f.write(jpg)
                except Exception:
                    pass

                atts.append((fname, jpg, "image/jpeg"))

            except Exception as e:
                msg = f"{label}: capture failed ({e})"
                print(f"[WARN] {msg}")
                errors.append(msg)

        browser.close()

    return atts, errors


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(
    run_prefix: str,
    atts: List[Attachment],
) -> Tuple[List[str], Optional[str]]:
    """
    R2へアップロードする。

    returns:
      all_urls:
        Notion本文・Discord投稿に使うURL一覧

      rep_url:
        NotionのR2 URLプロパティ用代表URL
    """
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep_url: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)

        url = make_url(key)
        urls.append(url)

        if rep_url is None:
            rep_url = url

    return urls, rep_url


# =============================================================================
# Notion
# =============================================================================
def notion_write_db(
    *,
    issue_base_jst: datetime,
    rjtd: str,
    run_prefix: str,
    rep_url: Optional[str],
    all_urls: List[str],
    errors: List[str],
) -> Optional[str]:
    """
    Notion DBへ1ページ作成する。

    区分:
      Guidance
    """
    if not notion_enabled():
        return None

    day = issue_base_jst.strftime("%Y%m%d")
    title = f"Guidance / {day} {issue_base_jst.strftime('%H:%M')} JST"

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]

    memo = "\n".join(memo_lines)

    page_id = create_db_row(
        title=title,
        category="Guidance",
        init_jst_iso=issue_base_jst.isoformat(),
        memo=memo,
        rjtd=rjtd,
        prefix=run_prefix,
        r2_url=rep_url or "",
        autogen=True,
        icon_emoji="📊",
    )

    if not page_id:
        return None

    # Notion API反映待ち
    time.sleep(1.0)

    try:
        append_heading(page_id, "ガイダンス画像", level=2)
        if all_urls:
            append_images(page_id, all_urls, chunk=10)
    except Exception as e:
        print(f"[WARN] append guidance images failed: {e}")

    try:
        append_heading(page_id, "元ページ", level=2)
        for _, label, url in GUIDANCE_TARGETS:
            append_bookmark(page_id, url, caption=label)
    except Exception as e:
        print(f"[WARN] append guidance bookmarks failed: {e}")

    return page_id


# =============================================================================
# Discord
# =============================================================================
def notify_discord_guidance_images(
    *,
    all_urls: List[str],
    rjtd: str,
    issue_base_jst: datetime,
) -> None:
    """
    Guidance画像をDiscordに投稿する。
    """
    if not discord_guidance_enabled():
        return

    init_jst = issue_base_jst.strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_guidance_webhook_url(),
        title="JMA Guidance / ガイダンス",
        image_urls=all_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst=init_jst,
    )


def notify_discord_guidance_complete(
    *,
    page_id: Optional[str],
    errors: List[str],
    attach_count: int,
) -> None:
    """
    Guidance完了通知。
    Notion URLは出さない。
    """
    if not discord_guidance_enabled():
        return

    post_discord_complete(
        webhook_url=discord_guidance_webhook_url(),
        category="Guidance",
        notion_url="",
        attach_count=attach_count,
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================
def main() -> None:
    page_id: Optional[str] = None
    all_urls: List[str] = []
    errors: List[str] = []

    try:
        print("=== Start JMA Guidance ===")

        base_jst = floor_to_guidance_base_jst(now_jst())
        issue_base_utc = base_jst.astimezone(timezone.utc)

        rjtd = issue_base_utc.strftime("%d%H%M")
        day = issue_base_utc.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        images, capture_errors = capture_guidance_pages()
        errors.extend(capture_errors)

        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url = upload_to_r2(run_prefix, images)

        if all_urls:
            page_id = notion_write_db(
                issue_base_jst=base_jst,
                rjtd=rjtd,
                run_prefix=run_prefix,
                rep_url=rep_url,
                all_urls=all_urls,
                errors=errors,
            )

        if page_id:
            print(f"[OK] Notion DB row created: {page_id}")
            print(f"[OK] Notion URL: {notion_page_url(page_id)}")
        else:
            print("[WARN] Notion page was not created")

        try:
            if all_urls:
                notify_discord_guidance_images(
                    all_urls=all_urls,
                    rjtd=rjtd,
                    issue_base_jst=base_jst,
                )

                if discord_guidance_enabled():
                    print(f"[OK] Discord guidance images sent: {len(all_urls)}")

            notify_discord_guidance_complete(
                page_id=page_id,
                errors=errors,
                attach_count=len(all_urls),
            )

            if discord_guidance_enabled():
                print("[OK] Discord guidance complete sent")

        except Exception as e:
            print(f"[WARN] Discord guidance send failed: {e}")

        if errors:
            print("[WARN] completed with errors:")
            for e in errors:
                print(f"  - {e}")

        print("=== Done JMA Guidance ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
