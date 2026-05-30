# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/weather_map.py
#
# Weathercaster / JMA Weather Map
# Custom Layout PNG Version / 5 outputs explicit / layout5 widened / JMA-left-column / JMA-left-column
#
# 出力は必ず次の5枚を基本にする:
#   ① 01_EMAGRAM.png
#   ② 02_AXJP140.png
#   ③ 03_AUPA20.png
#   ④ 04_LAYOUT_4_WEEKLY.png
#   ⑤ 05_LAYOUT_5_DASHBOARD.png  ※左列AUPQ35/AUPQ78はJMA直取得
# =============================================================================

from __future__ import annotations

import io
import json
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
    append_imported_images_from_urls,
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
JMA_NUMERIC_BASE_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap"
JMA_TKAISETU_URL = os.environ.get(
    "JMA_TKAISETU_URL",
    "https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_tanki_latest.pdf",
).strip()
DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/jma_weather_map"

# 既存workflowの JPEG_DPI をそのまま読めるようにしつつ、内部ではPDF_DPIとして扱う
PDF_DPI = int(os.environ.get("PDF_DPI", os.environ.get("JPEG_DPI", "220")))

PNG_OPTIMIZE = os.environ.get("PNG_OPTIMIZE", "1").lower() in ("1", "true", "yes", "on")
LAYOUT_GAP = int(os.environ.get("LAYOUT_GAP", "24"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "jma").strip().strip("/")

NOTION_IMPORT_IMAGES = os.environ.get("NOTION_IMPORT_IMAGES", "0").lower() in ("1", "true", "yes", "on")
NOTION_IMPORT_TIMEOUT_SECONDS = int(os.environ.get("NOTION_IMPORT_TIMEOUT_SECONDS", "180"))
NOTION_IMPORT_POLL_SECONDS = float(os.environ.get("NOTION_IMPORT_POLL_SECONDS", "2.0"))

WEATHERCASTER_USER = os.environ.get("WEATHERCASTER_USER", "").strip()
WEATHERCASTER_PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DISCORD_UPLOAD_AS_FILE = os.environ.get("DISCORD_UPLOAD_AS_FILE", "1").lower() in ("1", "true", "yes", "on")
DISCORD_JPEG_QUALITY = int(os.environ.get("DISCORD_JPEG_QUALITY", "92"))
DISCORD_MAX_UPLOAD_MB = float(os.environ.get("DISCORD_MAX_UPLOAD_MB", "8"))

# 4枚目・5枚目の結合画像は、Discordへ本体をアップロードせず、
# 小さいサムネイルだけ添付し、高解像度PNG本体はR2 URLを開く。
DISCORD_R2_PNG_LINK_FILENAMES = {
    "04_LAYOUT_4_WEEKLY",
    "05_LAYOUT_5_DASHBOARD",
}
DISCORD_THUMB_MAX_WIDTH = int(os.environ.get("DISCORD_THUMB_MAX_WIDTH", "1200"))
DISCORD_THUMB_JPEG_QUALITY = int(os.environ.get("DISCORD_THUMB_JPEG_QUALITY", "84"))

Attachment = Tuple[str, bytes, str]

OUTPUT_TITLES = [
    "① エマグラム",
    "② AXJP140",
    "③ AUPA20",
    "④ 週間4列結合",
    "⑤ 全部入り",
]

OUTPUT_FILENAMES = [
    "01_EMAGRAM",
    "02_AXJP140",
    "03_AUPA20",
    "04_LAYOUT_4_WEEKLY",
    "05_LAYOUT_5_DASHBOARD",
]


# =============================================================================
# Discord / 関連リンク設定
# =============================================================================
def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


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


def _discord_upload_limit_bytes() -> int:
    return int(DISCORD_MAX_UPLOAD_MB * 1024 * 1024)


def prepare_discord_upload_image(src_path: str) -> Tuple[str, str]:
    """
    Discord投稿用の画像を準備する。
    高解像度は維持しつつ、PNGが重い場合はJPEG化してサイズを抑える。
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    upload_dir = os.path.join(OUTPUT_DIR, "_discord_upload")
    os.makedirs(upload_dir, exist_ok=True)

    src_size = os.path.getsize(src_path)
    limit = _discord_upload_limit_bytes()
    if src_size <= limit:
        return src_path, "image/png"

    with Image.open(src_path) as im:
        rgb = im.convert("RGB")
        stem = os.path.splitext(os.path.basename(src_path))[0]

        qualities = []
        first_q = max(50, min(95, DISCORD_JPEG_QUALITY))
        for q in [first_q, 88, 84, 80, 76, 72, 68, 64, 60, 56, 52]:
            if q not in qualities:
                qualities.append(q)

        best_path = ""
        best_size = None

        for q in qualities:
            out_path = os.path.join(upload_dir, f"{stem}_q{q}.jpg")
            rgb.save(out_path, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)

            sz = os.path.getsize(out_path)
            if best_size is None or sz < best_size:
                best_size = sz
                best_path = out_path

            if sz <= limit:
                return out_path, "image/jpeg"

        return best_path, "image/jpeg"


def post_discord_file_image(webhook_url: str, title: str, image_path: str, mime: str) -> None:
    """
    Discord webhook に画像ファイルそのものを添付して送る。
    """
    with open(image_path, "rb") as f:
        payload = {
            "content": title,
            "allowed_mentions": {"parse": []},
        }
        r = requests.post(
            webhook_url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files={"file": (os.path.basename(image_path), f, mime)},
            timeout=180,
        )
        r.raise_for_status()


def make_discord_thumbnail(src_path: str) -> Tuple[str, str]:
    """
    4・5枚目用の小さい確認サムネイルを作る。
    本体の高解像度PNGはR2 URLで開くため、ここではDiscord表示用だけ軽くする。
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    thumb_dir = os.path.join(OUTPUT_DIR, "_discord_thumb")
    os.makedirs(thumb_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(src_path))[0]
    out_path = os.path.join(thumb_dir, f"{stem}_thumb.jpg")

    with Image.open(src_path) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        max_w = max(320, DISCORD_THUMB_MAX_WIDTH)

        if w > max_w:
            new_h = max(1, int(h * (max_w / w)))
            rgb = rgb.resize((max_w, new_h), Image.Resampling.LANCZOS)

        q = max(50, min(95, DISCORD_THUMB_JPEG_QUALITY))
        rgb.save(out_path, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)

    return out_path, "image/jpeg"


EMAGRAM_ENABLE = os.environ.get("EMAGRAM_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EMAGRAM_URL = os.environ.get("EMAGRAM_URL", "https://bk-pro.jp/images/ema/ema_aki_00.gif").strip()
EMAGRAM_FILENAME = os.environ.get("EMAGRAM_FILENAME", "ema_aki_00.gif").strip()

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


def jma_cycle_suffix(issue_dt_jst: datetime) -> str:
    """
    JMA数値予報天気図の00/12を決める。
      09:00 JST初期値 → 00UTC → _00
      21:00 JST初期値 → 12UTC → _12
    """
    return "00" if issue_dt_jst.hour == 9 else "12"


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


def fetch_pdf_pages(session: requests.Session, name: str) -> List[Image.Image]:
    """PDFをダウンロードして全ページのPIL Imageリストを返す"""
    url = f"{BASE_URL}/{name}.pdf"
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
        ct = (r.headers.get("Content-Type") or "").lower()

        if r.status_code == 200 and (r.content.startswith(b"%PDF") or "pdf" in ct):
            return [p.convert("RGB") for p in convert_from_bytes(r.content, dpi=PDF_DPI)]

        print(f"[NG] {name}: HTTP={r.status_code}, Content-Type={ct}, URL={url}")
    except Exception as e:
        print(f"[ERR] fetch {name}: {e}")

    return []


def fetch_jma_numeric_pdf_pages(code: str, cycle: str) -> List[Image.Image]:
    """
    気象庁の数値予報天気図PDFを取得して全ページのPIL Imageリストを返す。
      code : 'aupq35' / 'aupq78'
      cycle: '00' / '12'

    指定された cycle で取得できなかった場合は、
    反対側の cycle も試す。
      例: cycle='00' → 00 → 12
          cycle='12' → 12 → 00
    """
    code = code.lower().strip()
    preferred_cycle = cycle.strip()

    if preferred_cycle not in ("00", "12"):
        preferred_cycle = "00"

    fallback_cycle = "12" if preferred_cycle == "00" else "00"
    cycles = [preferred_cycle, fallback_cycle]

    for cyc in cycles:
        url = f"{JMA_NUMERIC_BASE_URL}/{code}_{cyc}.pdf"

        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0",
                    "Accept": "application/pdf,*/*",
                },
                timeout=60,
                allow_redirects=True,
            )
            ct = (r.headers.get("Content-Type") or "").lower()

            if r.status_code == 200 and (r.content.startswith(b"%PDF") or "pdf" in ct):
                pages = [p.convert("RGB") for p in convert_from_bytes(r.content, dpi=PDF_DPI)]
                print(f"[OK] JMA {code}_{cyc}: pages={len(pages)} URL={url}")
                return pages

            print(f"[NG] JMA {code}_{cyc}: HTTP={r.status_code}, Content-Type={ct}, URL={url}")

        except Exception as e:
            print(f"[ERR] JMA {code}_{cyc}: {e}")

    print(f"[NG] JMA {code}: both cycles failed ({preferred_cycle}, {fallback_cycle})")
    return []

def fetch_jma_direct_pdf_pages(url: str, label: str = "") -> List[Image.Image]:
    """
    認証不要の気象庁URLから直接PDFを取得して PIL Image リストを返す。
    TKAISETU など WCN 経由ではなく JMA 直取得するものに使う。
    """
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0",
                "Accept": "application/pdf,*/*",
            },
            timeout=60,
            allow_redirects=True,
        )
        ct = (r.headers.get("Content-Type") or "").lower()
        if r.status_code == 200 and (r.content.startswith(b"%PDF") or "pdf" in ct):
            pages = [p.convert("RGB") for p in convert_from_bytes(r.content, dpi=PDF_DPI)]
            print(f"[OK] JMA direct {label}: pages={len(pages)} URL={url}")
            return pages
        print(f"[NG] JMA direct {label}: HTTP={r.status_code}, Content-Type={ct}, URL={url}")
    except Exception as e:
        print(f"[ERR] JMA direct {label}: {e}")
    return []


def fetch_image_content(url: str) -> Optional[bytes]:
    """
    エマグラムなど、PDFではない画像ファイルを取得する。
    """
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 jma-weather-map-bot/1.0",
                "Accept": "image/*,*/*",
            },
            timeout=30,
            allow_redirects=True,
        )

        if r.status_code == 200 and r.content:
            print(f"[OK] image fetch: {url}")
            return r.content

        print(f"[NG] image HTTP {r.status_code}: {url}")

    except Exception as e:
        print(f"[ERR] image fetch: {e} ({url})")

    return None


# =============================================================================
# 共通画像処理
# =============================================================================
def pil_to_attachment(img: Image.Image, filename_without_ext: str) -> Attachment:
    """PIL ImageをPNG添付に変換する。PDF由来の細線・文字を保つためJPEG圧縮は使わない。"""
    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="PNG", optimize=PNG_OPTIMIZE)
    return (f"{filename_without_ext}.png", buf.getvalue(), "image/png")


def rename_attachment(att: Attachment, filename_without_ext: str) -> Attachment:
    _old_name, data, mime = att
    return (f"{filename_without_ext}.png", data, mime)


def append_output(images: List[Attachment], att: Attachment, index: int) -> None:
    """
    出力5枚を明示的に追加する。
    GitHub Actionsログ・R2・Discordで何枚目か分かるよう、ファイル名を固定する。
    """
    fixed = rename_attachment(att, OUTPUT_FILENAMES[index - 1])
    images.append(fixed)
    print(f"[OUT {index:02d}] {fixed[0]}")


def get_first_page_or_none(pages: List[Image.Image]) -> Optional[Image.Image]:
    return pages[0] if pages else None



def combine_vertical(images: List[Image.Image], *, gap: int = 0) -> Optional[Image.Image]:
    valid = [im.convert("RGB") for im in images if im is not None]
    if not valid:
        return None

    w = max(im.width for im in valid)
    h = sum(im.height for im in valid) + gap * (len(valid) - 1)

    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for im in valid:
        canvas.paste(im, ((w - im.width) // 2, y))
        y += im.height + gap

    return canvas


def combine_horizontal(images: List[Image.Image], *, gap: int = 0, valign: str = "top") -> Optional[Image.Image]:
    valid = [im.convert("RGB") for im in images if im is not None]
    if not valid:
        return None

    w = sum(im.width for im in valid) + gap * (len(valid) - 1)
    h = max(im.height for im in valid)

    canvas = Image.new("RGB", (w, h), "white")
    x = 0
    for im in valid:
        if valign == "center":
            y = (h - im.height) // 2
        else:
            y = 0
        canvas.paste(im, (x, y))
        x += im.width + gap

    return canvas


def resize_to_width(img: Image.Image, target_w: int) -> Image.Image:
    """縦横比を保ったまま、指定幅に合わせる。"""
    img = img.convert("RGB")
    if target_w <= 0 or img.width <= 0:
        return img
    target_h = max(1, int(img.height * (target_w / img.width)))
    return img.resize((target_w, target_h), Image.LANCZOS)


def pad_to_cell_width(img: Image.Image, cell_w: int, *, valign: str = "top") -> Image.Image:
    """
    画像自体は拡大縮小せず、セル幅だけをそろえる。
    幅を広げたいという要望に合わせ、足りない分は余白で持たせる。
    """
    img = img.convert("RGB")
    cell_w = max(cell_w, img.width)
    canvas = Image.new("RGB", (cell_w, img.height), "white")
    x = (cell_w - img.width) // 2
    y = 0
    canvas.paste(img, (x, y))
    return canvas


def normalize_row_to_columns(images: List[Optional[Image.Image]], col_w: int, *, gap: int = 0) -> Optional[Image.Image]:
    """
    3列を同じセル幅に揃えて横結合する。
    ここでは縮小よりも『幅を広げる』方針を優先し、画像は原寸維持・余白で調整する。
    """
    normalized: List[Image.Image] = []
    for im in images:
        if im is None:
            continue
        normalized.append(pad_to_cell_width(im, col_w, valign="top"))

    return combine_horizontal(normalized, gap=gap, valign="top")


# =============================================================================
# 特殊画像生成関数
# =============================================================================
def process_fxjp854_fit(
    pages: List[Image.Image],
    target_w: int,
    target_h: Optional[int] = None,
    *,
    gap: int = 0,
) -> Optional[Image.Image]:
    """
    FXJP854 は「1ページ目を上下に切断 → 左右に横並び → 中央配置」で作る。

    重要:
    - PDFが複数ページに変換されても、先頭ページだけを使う。
    - 4ページを横並びにはしない。
    - target_w に収まるように縮小する。
    - target_h が指定された場合は、その高さにも収まるように縮小し、
      白いキャンバスの中央に配置する。
    """
    if not pages:
        return None

    img = pages[0].convert("RGB")
    w, h = img.size
    mid_y = h // 2

    upper = img.crop((0, 0, w, mid_y))
    lower = img.crop((0, mid_y, w, h))

    joined = combine_horizontal([upper, lower], gap=gap, valign="top")
    if joined is None:
        return None

    # 幅・高さの上限に収まるように、縦横比維持で縮小する。
    scale = 1.0
    if target_w and joined.width > target_w:
        scale = min(scale, target_w / joined.width)
    if target_h and joined.height > target_h:
        scale = min(scale, target_h / joined.height)

    if scale < 1.0:
        new_w = max(1, int(joined.width * scale))
        new_h = max(1, int(joined.height * scale))
        joined = joined.resize((new_w, new_h), Image.LANCZOS)

    # target_h がある場合は、右側3列エリアの中で中央配置した完成行として返す。
    if target_h:
        canvas_w = max(target_w, joined.width)
        canvas_h = max(target_h, joined.height)
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        x = (canvas_w - joined.width) // 2
        y = (canvas_h - joined.height) // 2
        canvas.paste(joined, (x, y))
        return canvas

    return joined



def build_layout_4(session: requests.Session, errors: List[str]) -> Optional[Attachment]:
    """
    ④ 週間 4列結合
      1列目: SKAISETU 全ページ縦結合
      2列目: FEFE19
      3列目: FXXN519
      4列目: FZCX50
    """
    print("-> Building Layout 4 (Weekly Multicolumn)")

    skai_pages = fetch_pdf_pages(session, "SKAISETU")
    col1_img = combine_vertical(skai_pages, gap=LAYOUT_GAP) if skai_pages else None
    if col1_img is None:
        errors.append("Layout4: SKAISETU download/conversion failed")

    col2_img = get_first_page_or_none(fetch_pdf_pages(session, "FEFE19"))
    col3_img = get_first_page_or_none(fetch_pdf_pages(session, "FXXN519"))
    col4_img = get_first_page_or_none(fetch_pdf_pages(session, "FZCX50"))

    if col2_img is None:
        errors.append("Layout4: FEFE19 failed")
    if col3_img is None:
        errors.append("Layout4: FXXN519 failed")
    if col4_img is None:
        errors.append("Layout4: FZCX50 failed")

    canvas = combine_horizontal([col1_img, col2_img, col3_img, col4_img], gap=LAYOUT_GAP, valign="top")
    if canvas is None:
        return None

    return pil_to_attachment(canvas, "LAYOUT_4_WEEKLY")


def build_layout_5(session: requests.Session, errors: List[str]) -> Optional[Attachment]:
    """
    ⑤ 全部入り（TeamSABOTENスタイル・タブレット天気図完全再現版）
      左列: TKAISETU(WCN) / AUPQ35(JMA) / AUPQ78(JMA)
      上段: ASAS / FSAS24 / FSAS48
      中段: COMP12 / COMP36 / COMP72
      下段: FXJP854（上下分割→横並び）
    """
    print("-> Building Layout 5 (Perfect Dashboard Layout)")

    issue_dt_jst = issue_base_jst()
    cycle = jma_cycle_suffix(issue_dt_jst)
    print(f"[INFO] Layout5 JMA numeric cycle: {cycle}")

    # 1. 各パーツの読み込み
    # TKAISETU: WCN経由ではなく気象庁から直接取得
    tkai = get_first_page_or_none(fetch_jma_direct_pdf_pages(JMA_TKAISETU_URL, "TKAISETU"))
    aupq35 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("aupq35", cycle))
    aupq78 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("aupq78", cycle))

    asas = get_first_page_or_none(fetch_pdf_pages(session, "ASAS"))
    fsas24 = get_first_page_or_none(fetch_pdf_pages(session, "FSAS24"))
    fsas48 = get_first_page_or_none(fetch_pdf_pages(session, "FSAS48"))

    comp12 = get_first_page_or_none(fetch_pdf_pages(session, "COMP12"))
    comp36 = get_first_page_or_none(fetch_pdf_pages(session, "COMP36"))
    comp72 = get_first_page_or_none(fetch_pdf_pages(session, "COMP72"))

    # FXJP854はページリストを保持（right_w確定後に組み立てる）
    fxjp854_raw = fetch_pdf_pages(session, "FXJP854")

    # -------------------------------------------------------------------------
    # 2. 左列の構築（幅を TKAISETU に統一、各コマは縦横比を維持）
    # -------------------------------------------------------------------------
    left_target_w = tkai.width if tkai else 1000

    left_row1 = resize_to_width(tkai, left_target_w) if tkai is not None else None
    left_row2 = resize_to_width(aupq35, left_target_w) if aupq35 is not None else None
    left_row3 = resize_to_width(aupq78, left_target_w) if aupq78 is not None else None

    if left_row1 is None:
        errors.append("Layout5: TKAISETU missing (JMA direct)")
    if left_row2 is None:
        errors.append("Layout5: AUPQ35 missing")
    if left_row3 is None:
        errors.append("Layout5: AUPQ78 missing")

    # 各段の基準高さ = 左列コマの自然な高さ
    row1_h = left_row1.height if left_row1 is not None else 800
    row2_h = left_row2.height if left_row2 is not None else 800
    row3_h = left_row3.height if left_row3 is not None else 800

    if left_row1 is None:
        left_row1 = Image.new("RGB", (left_target_w, row1_h), "white")
    if left_row2 is None:
        left_row2 = Image.new("RGB", (left_target_w, row2_h), "white")
    if left_row3 is None:
        left_row3 = Image.new("RGB", (left_target_w, row3_h), "white")

    # -------------------------------------------------------------------------
    # 3. 右側・上段（ASAS / FSAS24 / FSAS48）: 左列上段の高さに揃えて3列横並び
    # -------------------------------------------------------------------------
    top_parts = [asas, fsas24, fsas48]
    candidates_top = [p.width for p in top_parts if p is not None]
    col_w_top = max(candidates_top) if candidates_top else 1200
    top_resized = []
    for p in top_parts:
        if p is not None:
            scaled = resize_to_width(p, col_w_top)
            top_resized.append(pad_to_height(scaled, row1_h))
        else:
            top_resized.append(Image.new("RGB", (col_w_top, row1_h), "white"))
    top_canvas = combine_horizontal(top_resized, gap=LAYOUT_GAP, valign="top")

    # -------------------------------------------------------------------------
    # 4. 右側・中段（COMP12 / COMP36 / COMP72）: 左列中段の高さに揃えて3列横並び
    # -------------------------------------------------------------------------
    mid_parts = [comp12, comp36, comp72]
    candidates_mid = [p.width for p in mid_parts if p is not None]
    col_w_mid = max(candidates_mid) if candidates_mid else 1200
    mid_resized = []
    for p in mid_parts:
        if p is not None:
            scaled = resize_to_width(p, col_w_mid)
            mid_resized.append(pad_to_height(scaled, row2_h))
        else:
            mid_resized.append(Image.new("RGB", (col_w_mid, row2_h), "white"))
    mid_canvas = combine_horizontal(mid_resized, gap=LAYOUT_GAP, valign="top")

    # -------------------------------------------------------------------------
    # 5. right_w を確定してから FXJP854 を組み立てる
    # -------------------------------------------------------------------------
    right_w = max(
        top_canvas.width if top_canvas else col_w_top * 3 + LAYOUT_GAP * 2,
        mid_canvas.width if mid_canvas else col_w_mid * 3 + LAYOUT_GAP * 2,
    )

    if fxjp854_raw:
        # FXJP854は「上下切断→横並び」。右側3列幅・左列3段目高さの中で中央配置する。
        fxjp854 = process_fxjp854_fit(
            fxjp854_raw,
            right_w,
            target_h=row3_h,
            gap=LAYOUT_GAP,
        )
    else:
        errors.append("Layout5: FXJP854 missing")
        fxjp854 = None

    if fxjp854 is None:
        fxjp854 = Image.new("RGB", (right_w, row3_h), "white")

    # left_row3 と fxjp854 の高さを最終同期
    final_row3_h = max(left_row3.height, fxjp854.height)
    if left_row3.height != final_row3_h:
        left_row3 = pad_to_height(left_row3, final_row3_h)
    if fxjp854.height != final_row3_h:
        fxjp854 = pad_to_height(fxjp854, final_row3_h)

    # -------------------------------------------------------------------------
    # 6. 左列を縦結合
    # -------------------------------------------------------------------------
    left_canvas = combine_vertical([left_row1, left_row2, left_row3], gap=LAYOUT_GAP)

    # -------------------------------------------------------------------------
    # 7. 右側ブロックを縦結合（中央揃えで貼り付け）
    # -------------------------------------------------------------------------
    valid_rows = [row for row in [top_canvas, mid_canvas, fxjp854] if row is not None]
    right_h = sum(row.height for row in valid_rows) + LAYOUT_GAP * max(0, len(valid_rows) - 1)
    right_canvas = Image.new("RGB", (right_w, right_h), "white")

    y = 0
    for row in valid_rows:
        x = (right_w - row.width) // 2
        right_canvas.paste(row, (x, y))
        y += row.height + LAYOUT_GAP

    # -------------------------------------------------------------------------
    # 8. 左列と右側ブロックの最終マージ
    # -------------------------------------------------------------------------
    if left_canvas is None:
        return pil_to_attachment(right_canvas, "LAYOUT_5_DASHBOARD")

    final_w = left_canvas.width + LAYOUT_GAP + right_canvas.width
    final_h = max(left_canvas.height, right_canvas.height)

    final_canvas = Image.new("RGB", (final_w, final_h), "white")
    final_canvas.paste(left_canvas, (0, 0))
    final_canvas.paste(right_canvas, (left_canvas.width + LAYOUT_GAP, 0))

    return pil_to_attachment(final_canvas, "LAYOUT_5_DASHBOARD")


def pad_to_height(img: Image.Image, target_h: int) -> Image.Image:
    """
    画像を白余白で target_h にそろえる。
    target_h より高い場合はクロップせず、縦横比維持で縮小する。
    """
    img = img.convert("RGB")
    if img.height > target_h:
        new_w = max(1, int(img.width * (target_h / img.height)))
        img = img.resize((new_w, target_h), Image.LANCZOS)

    if img.height == target_h:
        return img

    canvas = Image.new("RGB", (img.width, target_h), "white")
    canvas.paste(img, (0, 0))
    return canvas


# =============================================================================
# メイン出力構築
# =============================================================================
def build_outputs() -> Tuple[List[Attachment], List[str]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = weathercaster_session()
    images: List[Attachment] = []
    errors: List[str] = []

    # -------------------------------------------------------------------------
    # ① エマグラム 単体
    # -------------------------------------------------------------------------
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob = fetch_image_content(EMAGRAM_URL)
        if blob:
            try:
                with Image.open(io.BytesIO(blob)) as im:
                    im.seek(0)
                    append_output(images, pil_to_attachment(im, "EMAGRAM"), 1)
            except Exception as e:
                errors.append(f"EMAGRAM: conversion failed ({e})")
        else:
            errors.append("EMAGRAM: download failed")

    # -------------------------------------------------------------------------
    # ② AXJP140.pdf 単体
    # -------------------------------------------------------------------------
    axjp_pages = fetch_pdf_pages(session, "AXJP140")
    if axjp_pages:
        append_output(images, pil_to_attachment(axjp_pages[0], "AXJP140"), 2)
    else:
        errors.append("AXJP140: download failed")

    # -------------------------------------------------------------------------
    # ③ 数値 AUPA20 単体
    # -------------------------------------------------------------------------
    aupa_pages = fetch_pdf_pages(session, "AUPA20")
    if aupa_pages:
        append_output(images, pil_to_attachment(aupa_pages[0], "AUPA20"), 3)
    else:
        errors.append("AUPA20: download failed")

    # -------------------------------------------------------------------------
    # ④ 週間 4列結合
    # -------------------------------------------------------------------------
    layout4_att = build_layout_4(session, errors)
    if layout4_att:
        append_output(images, layout4_att, 4)

    # -------------------------------------------------------------------------
    # ⑤ 全部入り
    # -------------------------------------------------------------------------
    layout5_att = build_layout_5(session, errors)
    if layout5_att:
        append_output(images, layout5_att, 5)

    # ローカルへの一時デバッグ書き出し
    for fname, data, _ in images:
        try:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(data)
        except Exception:
            pass

    print(f"[OK] output image count: {len(images)}")
    print(f"[OK] output images: {[name for name, _, _ in images]}")

    return images, errors


# =============================================================================
# R2 / Notion / Discord 連携
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
        if rep_url is None and fname.lower().endswith((".png", ".jpg", ".jpeg")):
            rep_url = url

    if rep_url is None:
        rep_url = first_url

    return urls, rep_url


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
    memo = "\n".join(["ERROR:"] + [f"- {e}" for e in errors]) if errors else ""

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
        print(f"[WARN] links failed: {e}")

    try:
        if all_urls:
            if NOTION_IMPORT_IMAGES:
                items = []
                for idx, url in enumerate(all_urls):
                    fname = f"{OUTPUT_FILENAMES[idx]}.png" if idx < len(OUTPUT_FILENAMES) else f"image_{idx + 1}.png"
                    items.append((fname, url, "image/png"))

                append_imported_images_from_urls(
                    page_id,
                    items,
                    chunk=10,
                    timeout_seconds=NOTION_IMPORT_TIMEOUT_SECONDS,
                    poll_seconds=NOTION_IMPORT_POLL_SECONDS,
                )
            else:
                append_images(page_id, all_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] Notion image append/import failed: {e}")
        # 移行中の安全策: Notion取り込みに失敗したら従来の外部URL埋め込みへ戻す
        try:
            if all_urls:
                append_images(page_id, all_urls, chunk=30)
        except Exception as e2:
            print(f"[WARN] append_images fallback failed: {e2}")

    return page_id


def discord_links_text() -> str:
    return "\n\n".join(["**参考リンク**"] + [f"・{t}\n{u}" for t, u in DISCORD_LINKS])


def notify_discord_images(
    *,
    all_urls: List[str],
    rjtd: str,
    issue_dt_jst: datetime,
    notion_url: str = "",
) -> None:
    if not discord_jma_enabled():
        return

    init_jst = issue_dt_jst.strftime("%Y-%m-%d %H:%M JST")
    webhook_url = discord_jma_webhook_url()

    for idx, filename in enumerate(OUTPUT_FILENAMES):
        title = OUTPUT_TITLES[idx] if idx < len(OUTPUT_TITLES) else f"資料 {idx + 1}"
        src_path = os.path.join(OUTPUT_DIR, f"{filename}.png")

        # 4枚目・5枚目の結合画像は、JPG化した本体をDiscordへ上げない。
        # Discordには小さいサムネイルだけ添付し、本文のR2 PNG URLを開いて解析する。
        if filename in DISCORD_R2_PNG_LINK_FILENAMES:
            if idx < len(all_urls) and all_urls[idx]:
                highres_url = all_urls[idx]
                content = (
                    f"{init_jst} / {title}\\n"
                    f"高解像度PNG（R2 / 30日保存）:\\n"
                    f"{highres_url}"
                )

                if os.path.exists(src_path):
                    try:
                        thumb_path, thumb_mime = make_discord_thumbnail(src_path)
                        post_discord_file_image(
                            webhook_url=webhook_url,
                            title=content,
                            image_path=thumb_path,
                            mime=thumb_mime,
                        )
                    except Exception as e:
                        print(f"[WARN] Discord thumbnail upload failed: {src_path} / {e}")
                        post_discord_text(content)
                else:
                    post_discord_text(content)
                continue

            print(f"[WARN] R2 PNG URL missing for {filename}; fallback to file upload")

        # 1〜3枚目、またはR2 URLが無い場合は、従来どおりDiscordへファイル添付する。
        if DISCORD_UPLOAD_AS_FILE:
            if os.path.exists(src_path):
                try:
                    upload_path, mime = prepare_discord_upload_image(src_path)
                    post_discord_file_image(
                        webhook_url=webhook_url,
                        title=f"{init_jst} / {title}",
                        image_path=upload_path,
                        mime=mime,
                    )
                    continue
                except Exception as e:
                    print(f"[WARN] Discord file upload failed: {src_path} / {e}")

        # ファイル添付に失敗した場合は、R2 URL 埋め込みにフォールバックする。
        if idx < len(all_urls):
            try:
                post_discord_item_image_urls(
                    webhook_url=webhook_url,
                    title=f"{init_jst} / {title}",
                    image_urls=[all_urls[idx]],
                    notion_url="",
                    rjtd=rjtd,
                    init_jst="",
                )
            except Exception as e:
                print(f"[WARN] Discord URL post failed: {all_urls[idx]} / {e}")
        else:
            print(f"[WARN] Discord post skipped: no file and no URL for {filename}")

    summary_lines = []
    if notion_url:
        summary_lines.extend(["**Notionページ**", notion_url, ""])
    summary_lines.append(discord_links_text())
    post_discord_text("\\n".join(summary_lines))


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
    try:
        print("=== Start Weathercaster JMA Weather Map (Custom Layout PNG / 5 outputs) ===")

        issue_dt_jst = issue_base_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        images, errors = build_outputs()
        all_urls, rep_url = upload_to_r2(run_prefix, images)

        page_id = notion_write_db(
            issue_dt_jst=issue_dt_jst,
            rjtd=rjtd,
            run_prefix=run_prefix,
            rep_url=rep_url,
            all_urls=all_urls,
            errors=errors,
        )

        notion_url = notion_page_url(page_id) if page_id else ""
        if notion_url:
            print(f"[OK] Notion URL: {notion_url}")

        try:
            notify_discord_images(
                all_urls=all_urls,
                rjtd=rjtd,
                issue_dt_jst=issue_dt_jst,
                notion_url=notion_url,
            )
            notify_discord_complete(errors=errors, attach_count=len(images))
        except Exception as e:
            print(f"[WARN] Discord failed: {e}")

        if errors:
            print("[WARN] completed with errors:")
            for e in errors:
                print(f"  - {e}")

        print("=== Done ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
