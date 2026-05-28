# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/weather_map.py
#
# Weathercaster / JMA Weather Map:
#   Weathercaster PDF / GIF → PNG/JPG → R2 → Notion DB → Discord
#
# 今回の方針:
#   - ファイル名は weather_map.py のまま
#   - workflow / import / secrets は変更しない
#   - 8000x6300px の「全部のせ」PNGを1枚生成
#   - ASAS / FSAS24 / FSAS48 は上段
#   - COMP12 / COMP36 / COMP72 は上段実況の下側を含むメイン領域へ配置
#   - AUPA20 / AUPA25 / AUPN30 は縦結合せず、左列に単体配置
#   - FXJP854 はページを上下段に分けて横方向へ配置
#
# 出力:
#   ALL_IN_ONE_WEATHER_MAP.png
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import requests
from pdf2image import convert_from_bytes
from PIL import Image

from module.utils.r2_utils import put_bytes, make_url
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

# 全部のせPNG設定
ALL_IN_ONE_ENABLE = os.environ.get("ALL_IN_ONE_ENABLE", "1").lower() in ("1", "true", "yes", "on")
ALL_IN_ONE_WIDTH = int(os.environ.get("ALL_IN_ONE_WIDTH", "8000"))
ALL_IN_ONE_HEIGHT = int(os.environ.get("ALL_IN_ONE_HEIGHT", "6300"))
ALL_IN_ONE_FILENAME = os.environ.get("ALL_IN_ONE_FILENAME", "ALL_IN_ONE_WEATHER_MAP.png").strip()

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
        requests.post(discord_jma_webhook_url(), json={"content": content}, timeout=20)
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
DISCORD_LINKS = [
    ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
    ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
    ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
]

NOTION_LINKS = [
    ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
    ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
    ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
    ("気象庁 防災情報（秋田県）", "https://www.jma.go.jp/bosai/#pattern=default&area_type=offices&area_code=050000"),
    ("WCN各種気象情報", "https://www.weathercaster.jp/member/member_only/kisho_shiryo/"),
]


# =============================================================================
# 日時
# =============================================================================
def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(jst_tz())


def issue_base_jst() -> datetime:
    """
    GitHub Actions想定:
      05:30 JST → 前日21:00 JST初期値
      11:30 JST → 当日09:00 JST初期値
      17:30 JST → 当日09:00 JST初期値
      23:30 JST → 当日21:00 JST初期値
    """
    n = now_jst()
    if 10 <= n.hour < 20:
        return n.replace(hour=9, minute=0, second=0, microsecond=0)
    base = n.replace(hour=21, minute=0, second=0, microsecond=0)
    if n.hour < 10:
        base = base - timedelta(days=1)
    return base


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
    session.auth = (WEATHERCASTER_USER, WEATHERCASTER_PASS)
    return session


def weathercaster_pdf_url(name: str) -> str:
    return f"{BASE_URL}/{name}.pdf"


def fetch_weathercaster_pdf(session: requests.Session, name: str) -> Optional[bytes]:
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
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0"}, timeout=30)
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


def pil_to_png_attachment(img: Image.Image, filename: str) -> Attachment:
    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="PNG", optimize=True)
    return (filename, buf.getvalue(), "image/png")


def pdf_bytes_to_pil_images(pdf_bytes: bytes, *, force_all: bool = False) -> List[Image.Image]:
    pages = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not pages:
        return []
    if force_all:
        return [p.convert("RGB") for p in pages]
    return [pages[0].convert("RGB")]


def pdf_bytes_to_jpgs(pdf_bytes: bytes, base_filename: str, *, force_all: bool = False) -> List[Attachment]:
    pages = pdf_bytes_to_pil_images(pdf_bytes, force_all=force_all)
    out: List[Attachment] = []
    for idx, page in enumerate(pages, start=1):
        suffix = f"_p{idx:02d}" if force_all else ""
        out.append(pil_to_attachment(page, f"{base_filename}{suffix}"))
    return out


def gif_to_jpg_attachment(gif_bytes: bytes, base_filename: str) -> Attachment:
    with Image.open(io.BytesIO(gif_bytes)) as im:
        im.seek(0)
        return pil_to_attachment(im.convert("RGB"), base_filename)


def fit_image(img: Image.Image, box_w: int, box_h: int, *, allow_upscale: bool = True) -> Image.Image:
    """余白をそろえるため、指定ボックス内に縦横比維持で収める。"""
    img = img.convert("RGB")
    scale = min(box_w / img.width, box_h / img.height)
    if not allow_upscale:
        scale = min(scale, 1.0)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def paste_fit(
    canvas: Image.Image,
    img: Image.Image,
    box: Tuple[int, int, int, int],
    *,
    anchor: str = "center",
) -> None:
    x, y, w, h = box
    fitted = fit_image(img, w, h)

    if anchor == "top":
        px = x + (w - fitted.width) // 2
        py = y
    elif anchor == "left_top":
        px = x
        py = y
    else:
        px = x + (w - fitted.width) // 2
        py = y + (h - fitted.height) // 2

    canvas.paste(fitted, (px, py))


def crop_top_bottom_halves(img: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """FXJP854など、1ページ内の上下段を分ける。"""
    img = img.convert("RGB")
    w, h = img.size
    mid = h // 2
    return img.crop((0, 0, w, mid)), img.crop((0, mid, w, h))


def write_attachment_to_tmp(att: Attachment) -> None:
    fname, data, _ = att
    try:
        with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
            f.write(data)
    except Exception:
        pass


def fetch_pdf_images(
    *,
    session: requests.Session,
    name: str,
    errors: List[str],
    force_all: bool = False,
) -> List[Image.Image]:
    pdf = fetch_weathercaster_pdf(session, name)
    if not pdf:
        errors.append(f"{name}: download failed")
        return []
    try:
        imgs = pdf_bytes_to_pil_images(pdf, force_all=force_all)
        if not imgs:
            errors.append(f"{name}: conversion failed")
        return imgs
    except Exception as e:
        errors.append(f"{name}: conversion failed ({e})")
        return []


def add_pdf_item(*, session: requests.Session, images: List[Attachment], errors: List[str], name: str, force_all: bool = False) -> None:
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
    except Exception as e:
        errors.append(f"{name}: conversion failed ({e})")


# =============================================================================
# 全部のせレイアウト
# =============================================================================
def make_all_in_one_canvas(imgs: dict[str, List[Image.Image]], issue_dt_jst: datetime) -> Attachment:
    """
    8000x6300px固定の全部のせPNG。
    図2のように、左列に解説/数値、右側に実況・予想・週間・FXJPを敷き詰める。
    """
    W = ALL_IN_ONE_WIDTH
    H = ALL_IN_ONE_HEIGHT
    canvas = Image.new("RGB", (W, H), "white")

    # 余白は図2に近く、広すぎない設定
    margin = 150
    gap = 34

    left_w = 1550
    main_x = margin + left_w + gap
    main_w = W - main_x - margin

    top_h = 1450
    start_y = margin

    # 左上: 解説。SKAISETU優先、なければTKAISETU、なければエマグラム
    commentary = None
    for key in ("SKAISETU", "TKAISETU", "EMAGRAM"):
        if imgs.get(key):
            commentary = imgs[key][0]
            break
    if commentary:
        paste_fit(canvas, commentary, (margin, start_y, left_w, top_h), anchor="top")

    # 上段: 実況 ASAS / FSAS24 / FSAS48
    top_cell_w = (main_w - gap * 2) // 3
    for i, key in enumerate(["ASAS", "FSAS24", "FSAS48"]):
        if imgs.get(key):
            paste_fit(canvas, imgs[key][0], (main_x + i * (top_cell_w + gap), start_y, top_cell_w, top_h), anchor="center")

    # 中段以下
    grid_y = start_y + top_h + gap
    grid_h = H - grid_y - margin

    # 左列: AUPA20 / AUPA25 / AUPN30 / AXJP140 を縦結合せず単体で積む
    left_keys = ["AUPA20", "AUPA25", "AUPN30", "AXJP140"]
    left_cell_h = (grid_h - gap * (len(left_keys) - 1)) // len(left_keys)
    for i, key in enumerate(left_keys):
        if imgs.get(key):
            paste_fit(canvas, imgs[key][0], (margin, grid_y + i * (left_cell_h + gap), left_w, left_cell_h), anchor="center")

    # 右側メイン: 6列 x 5段を基本に敷き詰める
    cols = 6
    rows = 5
    cell_w = (main_w - gap * (cols - 1)) // cols
    cell_h = (grid_h - gap * (rows - 1)) // rows

    cells: List[Image.Image] = []

    # 1段目〜: COMP12 / COMP36 / COMP72 はページが複数あれば全部使う
    for key in ["COMP12", "COMP36", "COMP72"]:
        cells.extend(imgs.get(key, []))

    # 週間
    for key in ["FXXN519", "FZCX50", "FEFE19"]:
        cells.extend(imgs.get(key, []))

    # 解説の2枚目以降があれば入れる
    for key in ["SKAISETU", "TKAISETU"]:
        if len(imgs.get(key, [])) > 1:
            cells.extend(imgs[key][1:])

    # FXJP854は上下段に分け、それぞれ横に並ぶように最後の段へ入れる
    fx_imgs: List[Image.Image] = []
    for im in imgs.get("FXJP854", []):
        top, bottom = crop_top_bottom_halves(im)
        fx_imgs.extend([top, bottom])

    # まず通常セルを詰める。最後の1段はFXJP用に空ける。
    normal_capacity = cols * (rows - 1)
    normal_cells = cells[:normal_capacity]
    for idx, im in enumerate(normal_cells):
        r = idx // cols
        c = idx % cols
        paste_fit(canvas, im, (main_x + c * (cell_w + gap), grid_y + r * (cell_h + gap), cell_w, cell_h), anchor="center")

    # FXJP854: 下段で横結合気味に配置。2枚なら半幅ずつ、4枚なら4分割。
    fx_y = grid_y + (rows - 1) * (cell_h + gap)
    if fx_imgs:
        n = min(len(fx_imgs), 4)
        fx_w = (main_w - gap * (n - 1)) // n
        for i, im in enumerate(fx_imgs[:n]):
            paste_fit(canvas, im, (main_x + i * (fx_w + gap), fx_y, fx_w, cell_h), anchor="center")

    return pil_to_png_attachment(canvas, ALL_IN_ONE_FILENAME)


# =============================================================================
# 出力構築
# =============================================================================
def build_outputs() -> Tuple[List[Attachment], List[str]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = weathercaster_session()
    images: List[Attachment] = []
    errors: List[str] = []

    if ALL_IN_ONE_ENABLE:
        collected: dict[str, List[Image.Image]] = {}

        # エマグラム
        if EMAGRAM_ENABLE and EMAGRAM_URL:
            blob = fetch_image_content(EMAGRAM_URL)
            if blob:
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        im.seek(0)
                        collected["EMAGRAM"] = [im.convert("RGB")]
                except Exception as e:
                    errors.append(f"EMAGRAM: conversion failed ({e})")
            else:
                errors.append("EMAGRAM: download failed")

        # 全部のせに使う素材
        for name in [
            "SKAISETU", "TKAISETU",
            "ASAS", "FSAS24", "FSAS48",
            "AUPA20", "AUPA25", "AUPN30", "AXJP140",
            "COMP12", "COMP36", "COMP72",
            "FXXN519", "FZCX50", "FEFE19",
            "FXJP854",
        ]:
            # 解説とCOMP/FXJPは複数ページがあれば使えるように全ページ変換
            force_all = name in ("SKAISETU", "TKAISETU", "COMP12", "COMP36", "COMP72", "FXJP854")
            collected[name] = fetch_pdf_images(session=session, name=name, errors=errors, force_all=force_all)

        try:
            att = make_all_in_one_canvas(collected, issue_base_jst())
            write_attachment_to_tmp(att)
            images.append(att)
            return images, errors
        except Exception as e:
            errors.append(f"ALL_IN_ONE: failed ({e})")
            # 失敗時は従来形式にフォールバック

    # -------------------------------------------------------------------------
    # フォールバック: 従来の個別出力
    # -------------------------------------------------------------------------
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob = fetch_image_content(EMAGRAM_URL)
        if blob:
            try:
                base = EMAGRAM_FILENAME.replace(".gif", "")
                att = gif_to_jpg_attachment(blob, base)
                write_attachment_to_tmp(att)
                images.append(att)
            except Exception as e:
                errors.append(f"EMAGRAM: conversion failed ({e})")
        else:
            errors.append("EMAGRAM: download failed")

    for name in ["ASAS", "FSAS24", "FSAS48"]:
        add_pdf_item(session=session, images=images, errors=errors, name=name, force_all=False)

    # AUPAは縦結合せず単体
    for name in ["AUPA20", "AUPA25", "AUPN30", "AXJP140"]:
        add_pdf_item(session=session, images=images, errors=errors, name=name, force_all=False)

    for name in ["FXXN519", "FZCX50", "FEFE19"]:
        add_pdf_item(session=session, images=images, errors=errors, name=name, force_all=False)

    for name in ["SKAISETU", "TKAISETU"]:
        add_pdf_item(session=session, images=images, errors=errors, name=name, force_all=True)

    for name in ["COMP12", "COMP36", "COMP72", "FXJP854"]:
        add_pdf_item(session=session, images=images, errors=errors, name=name, force_all=True)

    return images, errors


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(run_prefix: str, atts: List[Attachment]) -> Tuple[List[str], Optional[str]]:
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep_url: Optional[str] = None
    first_url: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)
        urls.append(url)
        if first_url is None:
            first_url = url
        if rep_url is None and fname.lower().endswith((".jpg", ".jpeg", ".png")):
            rep_url = url

    if rep_url is None:
        rep_url = first_url
    return urls, rep_url


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
        append_heading(page_id, "関連リンク", level=2)
        for cap, url in NOTION_LINKS:
            append_bookmark(page_id, url, caption=cap)
    except Exception as e:
        print(f"[WARN] append links failed: {e}")

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
    for title, url in DISCORD_LINKS:
        lines.append(f"・{title}\n{url}")
    return "\n\n".join(lines)


def notify_discord_images(*, all_urls: List[str], rjtd: str, issue_dt_jst: datetime) -> None:
    if not discord_jma_enabled() or not all_urls:
        return

    init_jst = issue_dt_jst.strftime("%Y-%m-%d %H:%M JST")
    post_discord_item_image_urls(
        webhook_url=discord_jma_webhook_url(),
        title=init_jst,
        image_urls=all_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst="",
    )
    post_discord_text(discord_links_text())


def notify_discord_complete(*, errors: List[str], attach_count: int) -> None:
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
        print("=== Start Weathercaster JMA Weather Map ===")

        issue_dt_jst = issue_base_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        images, errors = build_outputs()

        rep_url: Optional[str] = None
        if images:
            all_urls, rep_url = upload_to_r2(run_prefix, images)

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
            notify_discord_images(all_urls=all_urls, rjtd=rjtd, issue_dt_jst=issue_dt_jst)
            notify_discord_complete(errors=errors, attach_count=len(all_urls))
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
