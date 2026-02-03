# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster PDF → JPG → R2 → Notion DB（wx 天気図 DB）
# - 代表1枚 + toggle全文
# - Slack / Mail 完全撤去
#
# DELIVERY_MODE=notion 前提
#
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict, Any

import requests
from pdf2image import convert_from_bytes

from r2_utils import put_bytes, make_url

from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    update_page_cover,
    append_heading,
    append_image,
    create_toggle_block,
    append_images_to_block,
)

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

PDF_FILES = [
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXXN519.pdf", "FZCX50.pdf", "FXJP854.pdf", "FEFE19.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf",
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "").strip()
PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
NOTION_DB_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()

# --- Notion property names ---
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "名前")
PROP_CATEGORY = os.environ.get("NOTION_PROP_CATEGORY", "区分")
PROP_INITJST = os.environ.get("NOTION_PROP_INIT_JST", "初期時刻（JST）")
PROP_MEMO = os.environ.get("NOTION_PROP_MEMO", "メモ")

PROP_R2URL = os.environ.get("NOTION_PROP_R2URL", "R2 URL")
PROP_AUTOGEN = os.environ.get("NOTION_PROP_AUTOGEN", "自動生成")
PROP_RJTD = os.environ.get("NOTION_PROP_RJTD", "RJTD")
PROP_PREFIX = os.environ.get("NOTION_PROP_PREFIX", "prefix")

Attachment = Tuple[str, bytes, str]


# ------------------------------------------------------------------

def _now_jst_iso() -> str:
    jst = timezone(offset=datetime.strptime("+0900", "%z").tzinfo.utcoffset(datetime.now()))
    return datetime.now(timezone.utc).astimezone(jst).isoformat()


def fetch_pdf_content(name: str) -> Optional[bytes]:
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        if r.status_code == 200:
            return r.content
        print(f"[NG] {name} HTTP {r.status_code}")
    except Exception as e:
        print(f"[ERR] {name}: {e}")
    return None


def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
) -> List[Attachment]:

    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not images:
        return []

    out: List[Attachment] = []

    if force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            out.append((f"{base_filename}_p{idx:02d}.jpg", buf.getvalue(), "image/jpeg"))
        return out

    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))
    return out


def build_outputs(today: str) -> Tuple[List[Attachment], List[str]]:

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []

    for name in PDF_FILES:
        pdf = fetch_pdf_content(name)
        if not pdf:
            errors.append(f"{name}: download failed")
            continue

        base = f"{today}_{name.replace('.pdf', '')}"

        force_all = name in ("SKAISETU.pdf", "TKAISETU.pdf")
        atts = pdf_bytes_to_jpgs(pdf, base, force_all=force_all)

        if not atts:
            errors.append(f"{name}: conversion failed")
            continue

        for fname, blob, _ in atts:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)

        images.extend(atts)

    return images, errors


def upload_to_r2(today: str, atts: List[Attachment]) -> Tuple[List[str], Optional[str]]:

    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep: Optional[str] = None

    run_prefix = f"weathercaster/{today}"

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)
        urls.append(url)
        if not rep:
            rep = url

    return urls, rep


def notion_write_db(
    today: str,
    rep_url: Optional[str],
    all_urls: List[str],
    errors: List[str],
) -> Optional[str]:

    if not notion_enabled() or not NOTION_DB_ID:
        return None

    title = f"Weathercaster 天気図 {today}"

    init_jst = _now_jst_iso()

    props: Dict[str, Any] = {
        PROP_TITLE: {"title": [{"type": "text", "text": {"content": title}}]},
        PROP_CATEGORY: {"select": {"name": "Weathercaster"}},
        PROP_INITJST: {"date": {"start": init_jst}},
        PROP_AUTOGEN: {"checkbox": True},
    }

    if all_urls:
        props[PROP_R2URL] = {"url": all_urls[0]}

    if errors:
        memo = "ERROR:\n" + "\n".join(f"- {e}" for e in errors)
        props[PROP_MEMO] = {"rich_text": [{"type": "text", "text": {"content": memo[:1900]}}]}

    page_id = create_db_row(
        database_id=NOTION_DB_ID,
        properties=props,
        rjtd="",
        prefix="",
        icon_emoji="🗺️",
    )

    if not page_id:
        return None

    if rep_url:
        update_page_cover(page_id, rep_url)

    append_heading(page_id, "代表画像", level=3)
    if rep_url:
        append_image(page_id, rep_url)

    append_heading(page_id, "全文画像", level=3)
    toggle_id = create_toggle_block(page_id, "▼ 全文画像を開く")
    if toggle_id:
        append_images_to_block(toggle_id, all_urls, chunk=30)

    return page_id


# ------------------------------------------------------------------

def main():

    today = datetime.utcnow().strftime("%Y%m%d")

    try:
        images, errors = build_outputs(today)

        all_urls: List[str] = []
        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url = upload_to_r2(today, images)

        if all_urls:
            notion_write_db(today, rep_url, all_urls, errors)

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
