# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster PDF → JPG → R2 → Notion DB（wx 天気図 DB）
# - 代表1枚 + toggle全文
# - Slack / Mail 完全撤去
#
# DELIVERY_MODE=notion 前提
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes

from r2_utils import put_bytes, make_url

from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    set_page_cover,
    append_heading,
    append_toggle,
    append_images,
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

# --- Notion property names ---
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "名前")
PROP_CATEGORY = os.environ.get("NOTION_PROP_CATEGORY", "区分")
PROP_INITJST = os.environ.get("NOTION_PROP_INIT_JST", "発行基準時刻")
PROP_MEMO = os.environ.get("NOTION_PROP_MEMO", "メモ")

PROP_AUTOGEN = os.environ.get("NOTION_PROP_AUTOGEN", "自動生成")
PROP_RJTD = os.environ.get("NOTION_PROP_RJTD", "RJTD")
PROP_PREFIX = os.environ.get("NOTION_PROP_PREFIX", "prefix")
PROP_R2URL = os.environ.get("NOTION_PROP_R2URL", "R2 URL")  # 任意。使わなければ空でOK

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


# ------------------------------------------------------------------

def jst_tz():
    return timezone(timedelta(hours=9))


def _now_jst_iso() -> str:
    return datetime.now(timezone.utc).astimezone(jst_tz()).isoformat()


def _httpdate_to_jst_iso(http_date: str) -> Optional[str]:
    """
    Last-Modified などの HTTP-date を JST ISO へ。
    例: 'Tue, 03 Feb 2026 00:10:00 GMT'
    """
    try:
        dt = parsedate_to_datetime(http_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(jst_tz()).isoformat()
    except Exception:
        return None


def fetch_pdf_content(name: str) -> Tuple[Optional[bytes], Optional[str], Optional[int]]:
    """
    returns: (content, last_modified_header, http_status)
    """
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        lm = r.headers.get("Last-Modified")
        if r.status_code == 200:
            return r.content, lm, r.status_code
        print(f"[NG] {name} HTTP {r.status_code}")
        return None, lm, r.status_code
    except Exception as e:
        print(f"[ERR] {name}: {e}")
        return None, None, None


def pdf_bytes_to_jpgs(pdf_bytes: bytes, base_filename: str, force_all: bool = False) -> List[Attachment]:
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

    # 代表は1枚目のみ
    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))
    return out


def build_outputs(today: str) -> Tuple[List[Attachment], List[str], Optional[str]]:
    """
    returns: (images, errors, issued_jst_iso_guess)
    issued_jst_iso_guess は、最初に取れた Last-Modified を優先して JST に変換した値（なければ None）
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []
    issued_jst_iso: Optional[str] = None

    for name in PDF_FILES:
        pdf, last_mod, st = fetch_pdf_content(name)
        if last_mod and not issued_jst_iso:
            issued_jst_iso = _httpdate_to_jst_iso(last_mod)

        if not pdf:
            errors.append(f"{name}: download failed (HTTP={st})")
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

    return images, errors, issued_jst_iso


def upload_to_r2(today: str, atts: List[Attachment]) -> Tuple[List[str], Optional[str], str]:
    """
    returns: (all_urls, rep_url, run_prefix)
    """
    run_prefix = f"weathercaster/{today}"
    if not R2_ENABLE:
        return [], None, run_prefix

    urls: List[str] = []
    rep: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)
        urls.append(url)
        if not rep:
            rep = url

    return urls, rep, run_prefix


def notion_write_db(today: str, rep_url: Optional[str], all_urls: List[str], errors: List[str], issued_jst_iso: Optional[str], run_prefix: str) -> Optional[str]:
    if not notion_enabled():
        return None

    title = f"Weathercaster 天気図 / {today}"

    # 発行基準時刻（推定）
    init_jst_iso = issued_jst_iso or _now_jst_iso()

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]
    if issued_jst_iso:
        memo_lines.append(f"issued_guess={issued_jst_iso}")
    memo = "\n".join(memo_lines)

    # create_db_row は ADV と同じ「引数型」で統一して使う
    page_id = create_db_row(
        title=title,
        category="Weathercaster",
        init_jst_iso=init_jst_iso,
        memo=memo,
        rjtd="",                 # Weathercasterは空でOK
        prefix=run_prefix,       # 追跡用（任意）
        r2_url="",               # 不要なら空でOK
        autogen=True,
    )

    if not page_id:
        return None

    if rep_url:
        set_page_cover(page_id, rep_url)

    append_heading(page_id, "代表画像", level=3)
    if rep_url:
        append_images(page_id, [rep_url], chunk=30)

    append_heading(page_id, "全文画像", level=3)
    toggle_id = append_toggle(page_id, "▼ 全文画像を開く")
    if toggle_id:
        append_images(toggle_id, all_urls, chunk=30)

    return page_id


# ------------------------------------------------------------------

def main():
    today = datetime.utcnow().strftime("%Y%m%d")

    try:
        images, errors, issued_jst_iso = build_outputs(today)

        all_urls: List[str] = []
        rep_url: Optional[str] = None
        run_prefix = f"weathercaster/{today}"

        if images:
            all_urls, rep_url, run_prefix = upload_to_r2(today, images)

        if all_urls:
            notion_write_db(today, rep_url, all_urls, errors, issued_jst_iso, run_prefix)

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
