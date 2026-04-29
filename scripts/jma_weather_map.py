# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weather_map.py
#
# Weathercaster / JMA Weather Map:
#   Weathercaster PDF / GIF → JPG → R2 → Notion DB → Discord
#
# 構成:
#   ① エマグラム
#   ② 実況      ASAS / FSAS24 / FSAS48
#   ③ 予想      COMP12 / COMP36 / COMP72 / FXJP854
#   ④ 数値      AUPA20 + AUPA25 + AUPN30 縦結合 / AXJP140
#   ⑤ 週間      FXXN519 / FZCX50 / FEFE19
#   ⑥ 解説      TKAISETU / SKAISETU
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from pdf2image import convert_from_bytes
from PIL import Image

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
# 基本設定
# =============================================================================
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/jma_weather_map"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "220"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "jma").strip().strip("/")

WEATHERCASTER_USER = os.environ.get("WEATHERCASTER_USER", "").strip()
WEATHERCASTER_PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()
WEATHERCASTER_DRIVE_FOLDER_ID = os.environ.get("WEATHERCASTER_DRIVE_FOLDER_ID", "").strip()

Attachment = Tuple[str, bytes, str]


# =============================================================================
# Discord設定
# =============================================================================
def env_bool(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def discord_jma_webhook_url() -> str:
    return (
        os.getenv("DISCORD_JMA_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEATHERCASTER_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    )


def discord_jma_enabled() -> bool:
    return env_bool("DISCORD_ENABLE", "0") and bool(discord_jma_webhook_url())


def post_discord_text(content: str) -> None:
    if not discord_jma_enabled():
        return

    try:
        requests.post(
            discord_jma_webhook_url(),
            json={"content": content},
            timeout=20,
        )
    except Exception as e:
        print(f"[WARN] Discord text send failed: {e}")


# =============================================================================
# エマグラム
# =============================================================================
EMAGRAM_ENABLE = os.environ.get("EMAGRAM_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EMAGRAM_URL = os.environ.get("EMAGRAM_URL", "https://bk-pro.jp/images/ema/ema_aki_00.gif").strip()
EMAGRAM_FILENAME = os.environ.get("EMAGRAM_FILENAME", "ema_aki_00.gif").strip()


# =============================================================================
# 関連リンク
# =============================================================================
AMEDAS_LINK = os.environ.get(
    "AMEDAS_LINK",
    "https://www.jma.go.jp/bosai/map.html#5/39.012/135/&elem=temp&contents=amedas",
).strip()

GUIDANCE_LINKS = [
    ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
    ("気象庁 数値予報天気図", "https://www.jma.go.jp/bosai/numericmap/"),
    ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
]


# =============================================================================
# 日時
# =============================================================================
def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(jst_tz())


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# Weathercasterログイン / 取得
# =============================================================================
def weathercaster_session() -> requests.Session:
    if not WEATHERCASTER_USER or not WEATHERCASTER_PASS:
        raise RuntimeError("WEATHERCASTER_USER / WEATHERCASTER_PASS is missing")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0",
            "Accept": "application/pdf,image/*,*/*",
        }
    )

    # Weathercaster の member_only は Basic 認証想定
    session.auth = (WEATHERCASTER_USER, WEATHERCASTER_PASS)
    return session


def weathercaster_pdf_url(name: str) -> str:
    return f"{BASE_URL}/{name}.pdf"


def fetch_weathercaster_pdf(
    session: requests.Session,
    name: str,
) -> Optional[bytes]:
    url = weathercaster_pdf_url(name)

    try:
        r = session.get(url, timeout=60, allow_redirects=True)

        ct = (r.headers.get("Content-Type") or "").lower()

        if r.status_code == 200 and (r.content.startswith(b"%PDF") or "pdf" in ct):
            return r.content

        print(f"[NG] {name}: HTTP={r.status_code}, Content-Type={ct}, URL={url}")
        return None

    except Exception as e:
        print(f"[ERR] {name}: {e}")
        return None


def fetch_image_content(url: str) -> Optional[bytes]:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0"},
            timeout=30,
        )

        if r.status_code == 200:
            return r.content

        print(f"[NG] image HTTP {r.status_code}: {url}")
        return None

    except Exception as e:
        print(f"[ERR] image: {e} ({url})")
        return None


# =============================================================================
# 画像変換
# =============================================================================
def pil_to_attachment(img: Image.Image, base_filename: str) -> Attachment:
    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return (f"{base_filename}.jpg", buf.getvalue(), "image/jpeg")


def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    *,
    force_all: bool = False,
) -> List[Attachment]:
    pages = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)

    if not pages:
        return []

    out: List[Attachment] = []

    if force_all:
        for idx, page in enumerate(pages, start=1):
            out.append(pil_to_attachment(page.convert("RGB"), f"{base_filename}_p{idx:02d}"))
        return out

    out.append(pil_to_attachment(pages[0].convert("RGB"), base_filename))
    return out


def gif_to_jpg_attachment(gif_bytes: bytes, base_filename: str) -> Attachment:
    with Image.open(io.BytesIO(gif_bytes)) as im:
        im.seek(0)
        im = im.convert("RGB")
        return pil_to_attachment(im, base_filename)


def combine_vertical_attachments(
    atts: List[Attachment],
    base_filename: str,
    *,
    padding: int = 16,
) -> Attachment:
    imgs: List[Image.Image] = []

    for _, blob, _ in atts:
        with Image.open(io.BytesIO(blob)) as im:
            imgs.append(im.convert("RGB"))

    if not imgs:
        raise ValueError("no images to combine")

    max_width = max(im.width for im in imgs)
    total_height = sum(im.height for im in imgs) + padding * (len(imgs) - 1)

    canvas = Image.new("RGB", (max_width, total_height), "white")

    y = 0
    for im in imgs:
        x = (max_width - im.width) // 2
        canvas.paste(im, (x, y))
        y += im.height + padding

    return pil_to_attachment(canvas, base_filename)


# =============================================================================
# 一時保存
# =============================================================================
def write_attachment_to_tmp(att: Attachment) -> None:
    fname, data, _ = att
    try:
        with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
            f.write(data)
    except Exception:
        pass


def add_pdf_item(
    *,
    session: requests.Session,
    images: List[Attachment],
    groups: Dict[str, List[str]],
    errors: List[str],
    section: str,
    name: str,
    force_all: bool = False,
) -> None:
    pdf = fetch_weathercaster_pdf(session, name)

    if not pdf:
        errors.append(f"{name}: download failed")
        return

    try:
        atts = pdf_bytes_to_jpgs(pdf, name, force_all=force_all)

        if not atts:
            errors.append(f"{name}: conversion failed")
            return

        for att in atts:
            write_attachment_to_tmp(att)
            images.append(att)
            groups.setdefault(section, []).append(att[0])

    except Exception as e:
        errors.append(f"{name}: conversion failed ({e})")


# =============================================================================
# 出力構築
# =============================================================================
def build_outputs() -> Tuple[List[Attachment], Dict[str, List[str]], List[str]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = weathercaster_session()

    images: List[Attachment] = []
    groups: Dict[str, List[str]] = {}
    errors: List[str] = []

    # -------------------------------------------------------------------------
    # ① エマグラム
    # -------------------------------------------------------------------------
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob = fetch_image_content(EMAGRAM_URL)

        if blob:
            try:
                base = EMAGRAM_FILENAME.replace(".gif", "")
                att = gif_to_jpg_attachment(blob, base)

                write_attachment_to_tmp(att)
                images.append(att)
                groups.setdefault("エマグラム", []).append(att[0])

            except Exception as e:
                errors.append(f"EMAGRAM: conversion failed ({e})")
        else:
            errors.append("EMAGRAM: download failed")

    # -------------------------------------------------------------------------
    # ② 実況
    # -------------------------------------------------------------------------
    for name in ["ASAS", "FSAS24", "FSAS48"]:
        add_pdf_item(
            session=session,
            images=images,
            groups=groups,
            errors=errors,
            section="実況",
            name=name,
            force_all=False,
        )

    # -------------------------------------------------------------------------
    # ③ 予想
    # -------------------------------------------------------------------------
    for name in ["COMP12", "COMP36", "COMP72", "FXJP854"]:
        add_pdf_item(
            session=session,
            images=images,
            groups=groups,
            errors=errors,
            section="予想",
            name=name,
            force_all=False,
        )

    # -------------------------------------------------------------------------
    # ④ 数値（上空 → 地上）
    # AUPA20 / AUPA25 / AUPN30 を縦結合して1枚
    # -------------------------------------------------------------------------
    upper_parts: List[Attachment] = []

    for name in ["AUPA20", "AUPA25", "AUPN30"]:
        pdf = fetch_weathercaster_pdf(session, name)

        if not pdf:
            errors.append(f"{name}: download failed")
            continue

        try:
            atts = pdf_bytes_to_jpgs(pdf, name, force_all=False)

            if atts:
                upper_parts.append(atts[0])
            else:
                errors.append(f"{name}: conversion failed")

        except Exception as e:
            errors.append(f"{name}: conversion failed ({e})")

    if upper_parts:
        try:
            upper_att = combine_vertical_attachments(
                upper_parts,
                "UPPER_AUPA20_AUPA25_AUPN30",
                padding=16,
            )
            write_attachment_to_tmp(upper_att)
            images.append(upper_att)
            groups.setdefault("数値", []).append(upper_att[0])
        except Exception as e:
            errors.append(f"UPPER combo: failed ({e})")

    add_pdf_item(
        session=session,
        images=images,
        groups=groups,
        errors=errors,
        section="数値",
        name="AXJP140",
        force_all=False,
    )

    # -------------------------------------------------------------------------
    # ⑤ 週間
    # -------------------------------------------------------------------------
    for name in ["FXXN519", "FZCX50", "FEFE19"]:
        add_pdf_item(
            session=session,
            images=images,
            groups=groups,
            errors=errors,
            section="週間",
            name=name,
            force_all=False,
        )

    # -------------------------------------------------------------------------
    # ⑥ 解説
    # -------------------------------------------------------------------------
    for name in ["TKAISETU", "SKAISETU"]:
        add_pdf_item(
            session=session,
            images=images,
            groups=groups,
            errors=errors,
            section="解説",
            name=name,
            force_all=True,
        )

    return images, groups, errors


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(
    run_prefix: str,
    atts: List[Attachment],
) -> Tuple[List[str], Optional[str], Dict[str, str]]:
    if not R2_ENABLE:
        return [], None, {}

    urls: List[str] = []
    url_by_filename: Dict[str, str] = {}
    rep_url: Optional[str] = None
    first_url: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)

        url = make_url(key)
        urls.append(url)
        url_by_filename[fname] = url

        if first_url is None:
            first_url = url

        if rep_url is None and fname.lower().endswith(".jpg"):
            rep_url = url

    if rep_url is None:
        rep_url = first_url

    return urls, rep_url, url_by_filename


# =============================================================================
# Notion
# =============================================================================
def notion_write_db(
    *,
    issue_dt_jst: datetime,
    rjtd: str,
    run_prefix: str,
    rep_url: Optional[str],
    all_urls: List[str],
    errors: List[str],
) -> Optional[str]:
    if not notion_enabled():
        return None

    day = issue_dt_jst.strftime("%Y%m%d")
    title = f"JMA / {day} {issue_dt_jst.strftime('%H:%M')} JST"

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]

    memo = "\n".join(memo_lines)

    page_id = create_db_row(
        title=title,
        category="JMA",
        init_jst_iso=issue_dt_jst.isoformat(),
        memo=memo,
        rjtd=rjtd,
        prefix=run_prefix,
        r2_url=rep_url or "",
        autogen=True,
        icon_emoji="🗺️",
    )

    if not page_id:
        return None

    time.sleep(1.0)

    try:
        if GUIDANCE_LINKS:
            append_heading(page_id, "関連リンク", level=2)
            for cap, url in GUIDANCE_LINKS:
                append_bookmark(page_id, url, caption=cap)
    except Exception as e:
        print(f"[WARN] append guidance links failed: {e}")

    try:
        if AMEDAS_LINK:
            append_heading(page_id, "アメダス", level=2)
            append_bookmark(page_id, AMEDAS_LINK, caption="気象庁 アメダス")
    except Exception as e:
        print(f"[WARN] append amedas link failed: {e}")

    try:
        if all_urls:
            append_images(page_id, all_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] append_images failed: {e}")

    return page_id


# =============================================================================
# Discord
# =============================================================================
def discord_links_text() -> str:
    lines = ["**参考リンク**"]

    for title, url in GUIDANCE_LINKS:
        lines.append(f"・{title}\n{url}")

    if AMEDAS_LINK:
        lines.append(f"・アメダス\n{AMEDAS_LINK}")

    return "\n\n".join(lines)


def notify_discord_sections(
    *,
    groups: Dict[str, List[str]],
    url_by_filename: Dict[str, str],
    rjtd: str,
    issue_dt_jst: datetime,
) -> None:
    if not discord_jma_enabled():
        return

    init_jst = issue_dt_jst.strftime("%Y-%m-%d %H:%M JST")

    order = [
        ("エマグラム", "エマグラム"),
        ("実況", "■実況"),
        ("予想", "■予想"),
        ("数値", "■数値（上空 → 地上）"),
        ("週間", "■週間"),
        ("解説", "■解説"),
    ]

    for key, title in order:
        filenames = groups.get(key, [])
        urls = [url_by_filename[f] for f in filenames if f in url_by_filename]

        if not urls:
            continue

        try:
            post_discord_item_image_urls(
                webhook_url=discord_jma_webhook_url(),
                title=title,
                image_urls=urls,
                notion_url="",
                rjtd=rjtd,
                init_jst=init_jst,
            )
        except Exception as e:
            print(f"[WARN] Discord section send failed ({title}): {e}")

    post_discord_text(discord_links_text())


def notify_discord_complete(
    *,
    errors: List[str],
    attach_count: int,
) -> None:
    if not discord_jma_enabled():
        return

    post_discord_complete(
        webhook_url=discord_jma_webhook_url(),
        category="JMA",
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
    url_by_filename: Dict[str, str] = {}
    errors: List[str] = []

    try:
        print("=== Start Weathercaster JMA Weather Map ===")

        issue_dt_jst = now_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        images, groups, errors = build_outputs()

        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url, url_by_filename = upload_to_r2(run_prefix, images)

        page_id = notion_write_db(
            issue_dt_jst=issue_dt_jst,
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
            notify_discord_sections(
                groups=groups,
                url_by_filename=url_by_filename,
                rjtd=rjtd,
                issue_dt_jst=issue_dt_jst,
            )

            notify_discord_complete(
                errors=errors,
                attach_count=len(all_urls),
            )

            if discord_jma_enabled():
                print("[OK] Discord sent")

        except Exception as e:
            print(f"[WARN] Discord send failed: {e}")

        if errors:
            print("[WARN] completed with errors:")
            for e in errors:
                print(f"  - {e}")

        print("=== Done Weathercaster JMA Weather Map ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
