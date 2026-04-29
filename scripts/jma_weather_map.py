# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weather_map.py
#
# JMA Weather Map:
#   JMA PDF / PNG / GIF → JPG → R2 → Notion DB → Discord
#
# 配信順:
#   ① エマグラム
#   ② 地上実況・予想
#   ③ 高層天気図（AUPA20 + AUPN30 縦結合）
#   ④ 断面図（AXJP130 / AXJP140）
#   ⑤ 数値予報
#        - 00・12時間
#        - 24・36時間
#        - 48・72時間
#        - FXJP854 単体
#   ⑥ 週間
#   ⑦ 解説
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Tuple, Optional

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
DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/jma_weather_map"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "jma").strip().strip("/")

JMA_UTC_OVERRIDE = os.environ.get("JMA_UTC_OVERRIDE", "").strip()

WEATHER_MAP_LIST_URL = "https://www.jma.go.jp/bosai/weather_map/data/list.json"
WEATHER_MAP_PNG_BASE_URL = "https://www.jma.go.jp/bosai/weather_map/data/png"
NWP_BASE_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap"

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


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# エマグラム
# =============================================================================
EMAGRAM_ENABLE = os.environ.get("EMAGRAM_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EMAGRAM_URL = os.environ.get("EMAGRAM_URL", "https://bk-pro.jp/images/ema/ema_aki_00.gif").strip()
EMAGRAM_FILENAME = os.environ.get("EMAGRAM_FILENAME", "ema_aki_00.gif").strip()


# =============================================================================
# リンクのみ
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
# 日時処理
# =============================================================================
def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(jst_tz())


def _httpdate_to_utc_dt(http_date: str) -> Optional[datetime]:
    try:
        dt = parsedate_to_datetime(http_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def select_jma_utc_run() -> str:
    if JMA_UTC_OVERRIDE in ("00", "12"):
        return JMA_UTC_OVERRIDE

    h = now_jst().hour
    return "00" if 10 <= h < 20 else "12"


def issue_base_utc_from_run(run_utc: str) -> datetime:
    n = now_jst()

    if run_utc == "00":
        base_jst = n.replace(hour=9, minute=0, second=0, microsecond=0)
        return base_jst.astimezone(timezone.utc)

    base_jst = n.replace(hour=21, minute=0, second=0, microsecond=0)

    if n.hour < 10:
        base_jst = base_jst - timedelta(days=1)

    return base_jst.astimezone(timezone.utc)


# =============================================================================
# URL生成
# =============================================================================
def nwp_pdf_url(code: str, run_utc: str) -> str:
    return f"{NWP_BASE_URL}/{code.lower()}_{run_utc}.pdf"


# =============================================================================
# 地上天気図 list.json
# =============================================================================
def build_surface_weather_map_targets() -> List[Tuple[str, str]]:
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(WEATHER_MAP_LIST_URL, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        near = data.get("near", {})

        result: List[Tuple[str, str]] = []

        items = [
            ("surface_now", near.get("now") or []),
            ("surface_fsas24", near.get("ft24") or []),
            ("surface_fsas48", near.get("ft48") or []),
        ]

        for base_name, files in items:
            if not files:
                print(f"[WARN] surface weather map missing: {base_name}")
                continue

            filename = files[-1]
            result.append((base_name, f"{WEATHER_MAP_PNG_BASE_URL}/{filename}"))

        return result

    except Exception as e:
        print(f"[WARN] surface weather map list fetch failed: {e}")
        return []


# =============================================================================
# 取得
# =============================================================================
def fetch_binary(name: str, url: str) -> Tuple[Optional[bytes], Optional[str], Optional[int], Optional[str]]:
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(url, headers=headers, timeout=60)

        lm = r.headers.get("Last-Modified")
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        if r.status_code == 200:
            return r.content, lm, r.status_code, ct

        print(f"[NG] {name} HTTP {r.status_code}: {url}")
        return None, lm, r.status_code, ct

    except Exception as e:
        print(f"[ERR] {name}: {e}")
        return None, None, None, None


def fetch_image_content(url: str) -> Tuple[Optional[bytes], Optional[str], Optional[int], Optional[str]]:
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(url, headers=headers, timeout=30)

        lm = r.headers.get("Last-Modified")
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        if r.status_code == 200:
            return r.content, lm, r.status_code, ct

        print(f"[NG] image HTTP {r.status_code}: {url}")
        return None, lm, r.status_code, ct

    except Exception as e:
        print(f"[ERR] image: {e} ({url})")
        return None, None, None, None


# =============================================================================
# 画像変換
# =============================================================================
def pdf_to_pil_first_page(pdf_bytes: bytes) -> Image.Image:
    pages = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not pages:
        raise ValueError("PDF has no pages")
    return pages[0].convert("RGB")


def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
) -> List[Attachment]:
    pages = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)

    if not pages:
        return []

    out: List[Attachment] = []

    if force_all:
        for idx, im in enumerate(pages, start=1):
            out.append(pil_to_attachment(im.convert("RGB"), f"{base_filename}_p{idx:02d}"))
        return out

    out.append(pil_to_attachment(pages[0].convert("RGB"), base_filename))
    return out


def png_bytes_to_pil(png_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(png_bytes)) as im:
        return im.convert("RGB")


def png_bytes_to_jpg(
    png_bytes: bytes,
    base_filename: str,
) -> Attachment:
    return pil_to_attachment(png_bytes_to_pil(png_bytes), base_filename)


def gif_to_jpg_bytes(gif_bytes: bytes, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(gif_bytes)) as im:
        im.seek(0)
        im = im.convert("RGB")

        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


def pil_to_attachment(img: Image.Image, base_filename: str) -> Attachment:
    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return (f"{base_filename}.jpg", buf.getvalue(), "image/jpeg")


def combine_vertical(images: List[Image.Image], padding: int = 16) -> Image.Image:
    rgb_images = [im.convert("RGB") for im in images if im is not None]

    if not rgb_images:
        raise ValueError("no images to combine")

    max_width = max(im.width for im in rgb_images)
    total_height = sum(im.height for im in rgb_images) + padding * (len(rgb_images) - 1)

    canvas = Image.new("RGB", (max_width, total_height), "white")

    y = 0
    for im in rgb_images:
        x = (max_width - im.width) // 2
        canvas.paste(im, (x, y))
        y += im.height + padding

    return canvas


def crop_half(img: Image.Image, side: str) -> Image.Image:
    img = img.convert("RGB")

    if side == "full":
        return img

    w, h = img.size
    mid = w // 2

    if side == "left":
        return img.crop((0, 0, mid, h))

    if side == "right":
        return img.crop((mid, 0, w, h))

    raise ValueError(f"unknown side: {side}")


def combine_two_columns(rows: List[Tuple[Image.Image, Image.Image]], padding: int = 16) -> Image.Image:
    left_width = max(left.width for left, right in rows)
    right_width = max(right.width for left, right in rows)

    row_heights = [
        max(left.height, right.height)
        for left, right in rows
    ]

    total_width = left_width + padding + right_width
    total_height = sum(row_heights) + padding * (len(rows) - 1)

    canvas = Image.new("RGB", (total_width, total_height), "white")

    y = 0
    for (left, right), row_h in zip(rows, row_heights):
        canvas.paste(left, (left_width - left.width, y))
        canvas.paste(right, (left_width + padding, y))
        y += row_h + padding

    return canvas


# =============================================================================
# 出力構築ヘルパー
# =============================================================================
def write_attachment_to_tmp(att: Attachment) -> None:
    fname, data, _ = att
    try:
        with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
            f.write(data)
    except Exception:
        pass


def add_png_as_jpg(
    *,
    images: List[Attachment],
    errors: List[str],
    lm_dts_all: List[datetime],
    base_name: str,
    url: str,
) -> None:
    blob, last_mod, st, ct = fetch_binary(base_name, url)

    if last_mod:
        dt = _httpdate_to_utc_dt(last_mod)
        if dt:
            lm_dts_all.append(dt)

    if not blob:
        errors.append(f"{base_name}: download failed (HTTP={st})")
        return

    try:
        att = png_bytes_to_jpg(blob, base_name)
        write_attachment_to_tmp(att)
        images.append(att)
    except Exception as e:
        errors.append(f"{base_name}: png conversion failed ({e})")


def add_pdf_as_jpg(
    *,
    images: List[Attachment],
    errors: List[str],
    lm_dts_all: List[datetime],
    base_name: str,
    url: str,
    force_all: bool = False,
) -> None:
    blob, last_mod, st, ct = fetch_binary(base_name, url)

    if last_mod:
        dt = _httpdate_to_utc_dt(last_mod)
        if dt:
            lm_dts_all.append(dt)

    if not blob:
        errors.append(f"{base_name}: download failed (HTTP={st})")
        return

    try:
        atts = pdf_bytes_to_jpgs(blob, base_name, force_all=force_all)

        if not atts:
            errors.append(f"{base_name}: conversion failed")
            return

        for att in atts:
            write_attachment_to_tmp(att)

        images.extend(atts)

    except Exception as e:
        errors.append(f"{base_name}: pdf conversion failed ({e})")


def add_vertical_pdf_combo(
    *,
    images: List[Attachment],
    errors: List[str],
    lm_dts_all: List[datetime],
    combo_name: str,
    items: List[Tuple[str, str]],
) -> None:
    pil_images: List[Image.Image] = []

    for item_name, url in items:
        blob, last_mod, st, ct = fetch_binary(item_name, url)

        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts_all.append(dt)

        if not blob:
            errors.append(f"{item_name}: download failed (HTTP={st})")
            continue

        try:
            pil_images.append(pdf_to_pil_first_page(blob))
        except Exception as e:
            errors.append(f"{item_name}: pdf conversion failed ({e})")

    if not pil_images:
        errors.append(f"{combo_name}: no images to combine")
        return

    try:
        combined = combine_vertical(pil_images)
        att = pil_to_attachment(combined, combo_name)
        write_attachment_to_tmp(att)
        images.append(att)

    except Exception as e:
        errors.append(f"{combo_name}: combine failed ({e})")


def add_pair_grid_pdf_combo(
    *,
    images: List[Attachment],
    errors: List[str],
    lm_dts_all: List[datetime],
    combo_name: str,
    rows: List[Tuple[Tuple[str, str, str], Tuple[str, str, str]]],
) -> None:
    """
    2カラム合成。

    rows:
      [
        ((左name, 左url, left/right/full), (右name, 右url, left/right/full)),
        ...
      ]
    """
    out_rows: List[Tuple[Image.Image, Image.Image]] = []

    for left_spec, right_spec in rows:
        row_imgs: List[Image.Image] = []

        for item_name, url, side in (left_spec, right_spec):
            blob, last_mod, st, ct = fetch_binary(item_name, url)

            if last_mod:
                dt = _httpdate_to_utc_dt(last_mod)
                if dt:
                    lm_dts_all.append(dt)

            if not blob:
                errors.append(f"{item_name}: download failed (HTTP={st})")
                break

            try:
                img = pdf_to_pil_first_page(blob)
                img = crop_half(img, side)
                row_imgs.append(img)
            except Exception as e:
                errors.append(f"{item_name}: pdf crop failed ({e})")
                break

        if len(row_imgs) == 2:
            out_rows.append((row_imgs[0], row_imgs[1]))

    if not out_rows:
        errors.append(f"{combo_name}: no images to combine")
        return

    try:
        combined = combine_two_columns(out_rows)
        att = pil_to_attachment(combined, combo_name)
        write_attachment_to_tmp(att)
        images.append(att)

    except Exception as e:
        errors.append(f"{combo_name}: combine failed ({e})")


# =============================================================================
# 出力構築
# =============================================================================
def build_outputs(run_utc: str) -> Tuple[List[Attachment], List[str], Optional[datetime]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []
    lm_dts_all: List[datetime] = []

    # -------------------------------------------------------------------------
    # ① 地上天気図
    # -------------------------------------------------------------------------
    surface_targets = build_surface_weather_map_targets()

    for base_name, url in surface_targets:
        add_png_as_jpg(
            images=images,
            errors=errors,
            lm_dts_all=lm_dts_all,
            base_name=base_name,
            url=url,
        )

    # -------------------------------------------------------------------------
    # ② 高層天気図：AUPA20 + AUPN30 縦結合
    # -------------------------------------------------------------------------
    add_vertical_pdf_combo(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        combo_name=f"upper_aupa20_aupn30_{run_utc}",
        items=[
            (f"aupa20_{run_utc}", nwp_pdf_url("aupa20", run_utc)),
            (f"aupn30_{run_utc}", nwp_pdf_url("aupn30", run_utc)),
        ],
    )

    # -------------------------------------------------------------------------
    # ③ 断面図：AXJP130 / AXJP140
    # -------------------------------------------------------------------------
    add_pdf_as_jpg(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        base_name=f"axjp130_{run_utc}",
        url=nwp_pdf_url("axjp130", run_utc),
        force_all=False,
    )

    add_pdf_as_jpg(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        base_name=f"axjp140_{run_utc}",
        url=nwp_pdf_url("axjp140", run_utc),
        force_all=False,
    )

    # -------------------------------------------------------------------------
    # ④ 数値予報：00・12時間
    #
    # 左列：AUPQ35 / AUPQ78（解析）
    # 右列：FXFE5782 / FXFE502 の左半分（12時間）
    # -------------------------------------------------------------------------
    add_pair_grid_pdf_combo(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        combo_name=f"forecast_00_12_{run_utc}",
        rows=[
            (
                (f"aupq35_{run_utc}", nwp_pdf_url("aupq35", run_utc), "full"),
                (f"fxfe5782_{run_utc}", nwp_pdf_url("fxfe5782", run_utc), "left"),
            ),
            (
                (f"aupq78_{run_utc}", nwp_pdf_url("aupq78", run_utc), "full"),
                (f"fxfe502_{run_utc}", nwp_pdf_url("fxfe502", run_utc), "left"),
            ),
        ],
    )

    # -------------------------------------------------------------------------
    # ⑤ 数値予報：24・36時間
    #
    # 左列：FXFE5782 / FXFE502 の右半分（24時間）
    # 右列：FXFE5784 / FXFE504 の左半分（36時間）
    # -------------------------------------------------------------------------
    add_pair_grid_pdf_combo(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        combo_name=f"forecast_24_36_{run_utc}",
        rows=[
            (
                (f"fxfe5782_{run_utc}", nwp_pdf_url("fxfe5782", run_utc), "right"),
                (f"fxfe5784_{run_utc}", nwp_pdf_url("fxfe5784", run_utc), "left"),
            ),
            (
                (f"fxfe502_{run_utc}", nwp_pdf_url("fxfe502", run_utc), "right"),
                (f"fxfe504_{run_utc}", nwp_pdf_url("fxfe504", run_utc), "left"),
            ),
        ],
    )

    # -------------------------------------------------------------------------
    # ⑥ 数値予報：48・72時間
    #
    # 左列：FXFE5784 / FXFE504 の右半分（48時間）
    # 右列：FXFE577 / FXFE507（72時間）
    # -------------------------------------------------------------------------
    add_pair_grid_pdf_combo(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        combo_name=f"forecast_48_72_{run_utc}",
        rows=[
            (
                (f"fxfe5784_{run_utc}", nwp_pdf_url("fxfe5784", run_utc), "right"),
                (f"fxfe577_{run_utc}", nwp_pdf_url("fxfe577", run_utc), "full"),
            ),
            (
                (f"fxfe504_{run_utc}", nwp_pdf_url("fxfe504", run_utc), "right"),
                (f"fxfe507_{run_utc}", nwp_pdf_url("fxfe507", run_utc), "full"),
            ),
        ],
    )

    # -------------------------------------------------------------------------
    # ⑦ FXJP854 単体
    # -------------------------------------------------------------------------
    add_pdf_as_jpg(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        base_name=f"fxjp854_{run_utc}",
        url=nwp_pdf_url("fxjp854", run_utc),
        force_all=False,
    )

    # -------------------------------------------------------------------------
    # ⑧ 週間系 PNG → JPG
    # -------------------------------------------------------------------------
    weekly_pngs = [
        ("fefe19", f"{NWP_BASE_URL}/fefe19.png"),
        ("fzcx50", f"{NWP_BASE_URL}/fzcx50.png"),
        ("fxxn519", f"{NWP_BASE_URL}/fxxn519.png"),
    ]

    for base_name, url in weekly_pngs:
        add_png_as_jpg(
            images=images,
            errors=errors,
            lm_dts_all=lm_dts_all,
            base_name=base_name,
            url=url,
        )

    # -------------------------------------------------------------------------
    # ⑨ 解説資料 PDF
    # -------------------------------------------------------------------------
    add_pdf_as_jpg(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        base_name="kaisetsu_tanki",
        url="https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_tanki_latest.pdf",
        force_all=True,
    )

    add_pdf_as_jpg(
        images=images,
        errors=errors,
        lm_dts_all=lm_dts_all,
        base_name="kaisetsu_shukan",
        url="https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_shukan_latest.pdf",
        force_all=True,
    )

    # -------------------------------------------------------------------------
    # ⑩ エマグラムを先頭に追加
    # -------------------------------------------------------------------------
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob, last_mod, st, ct = fetch_image_content(EMAGRAM_URL)

        if blob:
            try:
                jpg_blob = gif_to_jpg_bytes(blob, quality=JPEG_QUALITY)
                jpg_name = EMAGRAM_FILENAME.replace(".gif", ".jpg")
                att = (jpg_name, jpg_blob, "image/jpeg")

                images.insert(0, att)
                write_attachment_to_tmp(att)

            except Exception as e:
                print(f"[WARN] emagram convert failed: {e}")
        else:
            errors.append(f"EMAGRAM: download failed (HTTP={st})")

    issued_dt_utc_guess: Optional[datetime] = max(lm_dts_all) if lm_dts_all else None

    return images, errors, issued_dt_utc_guess


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(
    run_prefix: str,
    atts: List[Attachment],
) -> Tuple[List[str], Optional[str]]:
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep_url: Optional[str] = None
    first_url: Optional[str] = None
    first_jpeg_url: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)

        url = make_url(key)
        urls.append(url)

        if first_url is None:
            first_url = url

        if first_jpeg_url is None and mime == "image/jpeg":
            first_jpeg_url = url

        if rep_url is None and fname.lower().endswith("_cover.jpg"):
            rep_url = url

    if rep_url is None:
        rep_url = first_jpeg_url or first_url

    return urls, rep_url


# =============================================================================
# Notion
# =============================================================================
def notion_write_db(
    issue_base_utc: datetime,
    rjtd: str,
    run_prefix: str,
    rep_url: Optional[str],
    all_urls: List[str],
    errors: List[str],
) -> Optional[str]:
    if not notion_enabled():
        return None

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    day = issue_base_utc.strftime("%Y%m%d")

    title = f"JMA / {day} {issue_base_jst.strftime('%H:%M')} JST"

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]

    memo = "\n".join(memo_lines)

    page_id = create_db_row(
        title=title,
        category="JMA",
        init_jst_iso=issue_base_jst.isoformat(),
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
def notify_discord_jma_images(
    *,
    all_urls: List[str],
    rjtd: str,
    issue_base_utc: datetime,
) -> None:
    if not discord_jma_enabled():
        return

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    init_jst = issue_base_jst.strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_jma_webhook_url(),
        title="JMA 天気図",
        image_urls=all_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst=init_jst,
    )


def notify_discord_jma_complete(
    *,
    page_id: Optional[str],
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
    errors: List[str] = []

    try:
        print("=== Start JMA Weather Map ===")

        run_utc = select_jma_utc_run()
        print(f"[INFO] selected JMA run: {run_utc}UTC")

        images, errors, issued_guess_utc = build_outputs(run_utc)

        issue_base_utc = issue_base_utc_from_run(run_utc)

        rjtd = issue_base_utc.strftime("%d%H%M")
        day = issue_base_utc.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url = upload_to_r2(run_prefix, images)

        if all_urls or AMEDAS_LINK or GUIDANCE_LINKS:
            page_id = notion_write_db(
                issue_base_utc=issue_base_utc,
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
                notify_discord_jma_images(
                    all_urls=all_urls,
                    rjtd=rjtd,
                    issue_base_utc=issue_base_utc,
                )

                if discord_jma_enabled():
                    print(f"[OK] Discord images sent: {len(all_urls)}")

            notify_discord_jma_complete(
                page_id=page_id,
                errors=errors,
                attach_count=len(all_urls),
            )

            if discord_jma_enabled():
                print("[OK] Discord complete sent")

        except Exception as e:
            print(f"[WARN] Discord send failed: {e}")

        if errors:
            print("[WARN] completed with errors:")
            for e in errors:
                print(f"  - {e}")

        print("=== Done JMA Weather Map ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
