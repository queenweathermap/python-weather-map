# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/weather_map.py
#
# Weathercaster / JMA Weather Map
# Custom Layout PNG Version / 5 outputs explicit / layout5 widened / JMA-left-column / JMA-left-column
#
# 出力は必ず次の4枚を基本にする（エマグラムは別リポジトリへ切り出し済み）:
#   ① 02_AXJP140.png
#   ② 03_AUPA20.png
#   ③ 04_LAYOUT_4_WEEKLY.png
#   ④ 05_LAYOUT_5_DASHBOARD.png  ※左列AUPQ35/AUPQ78はJMA直取得
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
from PIL import Image, ImageDraw, ImageFont

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
from module.utils.notion_subscribers import get_active_discord_ids, get_active_emails
from module.utils.discord_dm import send_dm_to_all
from module.utils.onesignal_push import send_push_to_all
from module.utils.recent_items import record_recent_item


# =============================================================================
# 基本設定
# =============================================================================
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"
JMA_NUMERIC_BASE_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap"
JMA_TKAISETU_URL = os.environ.get(
    "JMA_TKAISETU_URL",
    "https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_tanki_latest.pdf",
).strip()
JMA_ASAS_MONO_URL = "https://www.data.jma.go.jp/yoho/data/wxchart/quick/ASAS_MONO.pdf"
JMA_FSAS24_MONO_URL = "https://www.data.jma.go.jp/yoho/data/wxchart/quick/FSAS24_MONO_ASIA.pdf"
JMA_FSAS48_MONO_URL = "https://www.data.jma.go.jp/yoho/data/wxchart/quick/FSAS48_MONO_ASIA.pdf"
JMA_SKAISETU_URL = "https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_shukan_latest.pdf"
JMA_FEFE19_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fefe19.png"
JMA_FXXN519_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxxn519.png"
JMA_FZCX50_URL = "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fzcx50.png"
DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/jma_weather_map"

# 既存workflowの JPEG_DPI をそのまま読めるようにしつつ、内部ではPDF_DPIとして扱う
PDF_DPI = int(os.environ.get("PDF_DPI", os.environ.get("JPEG_DPI", "220")))

PNG_OPTIMIZE = os.environ.get("PNG_OPTIMIZE", "1").lower() in ("1", "true", "yes", "on")
LAYOUT_GAP = int(os.environ.get("LAYOUT_GAP", "24"))
LAYOUT5_TRIM_PAD = int(os.environ.get("LAYOUT5_TRIM_PAD", "0"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
# R2キー先頭の prefix（weathermap 等）は r2_utils.normalize_key() が R2_PREFIX env から
# 自動付与する。ここで付けると weathermap/weathermap/... のように二重になるため付けない。

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
    "06_LAYOUT_5_DASHBOARD",
    "07_DASHBOARD_JMA_DIRECT",
}

# 有料DM配信は気象庁の一般公開データのみで構成された画像に限定する。
# 06_LAYOUT_5_DASHBOARD はWCN（Weathercaster.jp会員限定ページ）経由のため対象外。
# 04_LAYOUT_4_WEEKLY / 07_DASHBOARD_JMA_DIRECT はいずれもWCNを一切経由せず
# 気象庁の公開データのみで組み立てているため、DM配信の対象にする。
DM_SAFE_FILENAMES = {
    "04_LAYOUT_4_WEEKLY",
    "07_DASHBOARD_JMA_DIRECT",
}

# PWA配信履歴（Notion「PWA配信履歴」DB）に記録する際のカテゴリ名。
# 選択肢はNotion側のselectプロパティと一致させる必要がある。
PWA_CATEGORY_BY_FILENAME = {
    "07_DASHBOARD_JMA_DIRECT": "全部入り天気図",
    "04_LAYOUT_4_WEEKLY": "週間天気予報資料",
}
DISCORD_THUMB_MAX_WIDTH = int(os.environ.get("DISCORD_THUMB_MAX_WIDTH", "1200"))
DISCORD_THUMB_JPEG_QUALITY = int(os.environ.get("DISCORD_THUMB_JPEG_QUALITY", "84"))

Attachment = Tuple[str, bytes, str]

# 04_LAYOUT_4_WEEKLY（週間4列結合）は scripts/jma_layout4_weekly.py / main_layout4()
# として別スクリプト・別スケジュール（1日1回・JST正午、SKAISETUの10時頃更新に対応）に、
# 07_DASHBOARD_JMA_DIRECT（気象庁直接取得版・全部入り）は WCN を一切経由しないため、
# scripts/jma_dashboard_direct.py / main_dashboard_jma() として別スクリプト・別スケジュール
# （1日4回、TKAISETU発表とUTC 00/12時サイクルの両方に対応）に、それぞれ分離している。
# 06_LAYOUT_5_DASHBOARD（WCN版「全部入り」）は07が気象庁公開データのみで同等のレイアウトを
# 再現できるようになったため、公開投稿・Notionとも廃止した（build_layout_5()自体は
# 参考として残しているが、build_outputs()からは呼び出していない）。
# ここ(OUTPUT_FILENAMES/NOTION_ORDER)には含めない。
OUTPUT_FILENAMES = [
    "02_AXJP140",
    "03_AUPA20",
]

# Discord に送る画像とタイトル（AXJP140・AUPA20 は Notion のみ）
DISCORD_TITLES = {
    "04_LAYOUT_4_WEEKLY": "週間4列結合",
    "07_DASHBOARD_JMA_DIRECT": "高層天気図・数値予報天気図 結合図",
}
DISCORD_SKIP_FILENAMES = {"02_AXJP140", "03_AUPA20"}

# Notion に流し込む順序・ラベル・ファイル名（まる数字なし）
NOTION_ORDER = [
    ("03_AUPA20",             "AUPA20",       "AUPA20"),
    ("02_AXJP140",            "AXJP140",      "AXJP140"),
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
    r = requests.post(
        discord_jma_webhook_url(),
        json={"content": content, "allowed_mentions": {"parse": []}},
        timeout=60,
    )
    r.raise_for_status()


def post_discord_text_no_embed(content: str) -> None:
    """
    URLは文字として表示しつつ、Discord側の自動プレビューを抑制する。
    サムネイルを別添付する4・5枚目用。
    """
    if not discord_jma_enabled():
        return
    r = requests.post(
        discord_jma_webhook_url(),
        json={
            "content": content,
            "allowed_mentions": {"parse": []},
            "flags": 4,
        },
        timeout=60,
    )
    r.raise_for_status()


def post_discord_file_image(
    webhook_url: str,
    title: str,
    image_path: str,
    mime: str,
    *,
    suppress_embeds: bool = False,
) -> None:
    """
    Discord webhook に画像ファイルを1枚添付して送る。
    suppress_embeds=True の場合、本文中URLの自動プレビューを抑制する。
    """
    payload = {
        "content": title,
        "allowed_mentions": {"parse": []},
    }
    if suppress_embeds:
        # Discord SUPPRESS_EMBEDS。
        # 添付画像は表示し、本文URLの自動プレビューだけ抑制する。
        payload["flags"] = 4

    with open(image_path, "rb") as f:
        r = requests.post(
            webhook_url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files={"file": (os.path.basename(image_path), f, mime)},
            timeout=180,
        )
    r.raise_for_status()


def prepare_discord_upload_image(src_path: str) -> Tuple[str, str]:
    """
    Discord添付用。
    PNGが上限内ならそのまま、超える場合は画素数を維持してJPEG化する。
    それでも大きい場合だけ段階的に品質を下げる。
    """
    max_bytes = max(1, DISCORD_MAX_UPLOAD_MB) * 1024 * 1024

    if os.path.getsize(src_path) <= max_bytes:
        ext = os.path.splitext(src_path)[1].lower()
        if ext == ".png":
            return src_path, "image/png"
        if ext in (".jpg", ".jpeg"):
            return src_path, "image/jpeg"
        if ext == ".gif":
            return src_path, "image/gif"

    out_dir = os.path.join(OUTPUT_DIR, "_discord_upload")
    os.makedirs(out_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(src_path))[0]
    out_path = os.path.join(out_dir, f"{stem}_discord.jpg")

    with Image.open(src_path) as im:
        rgb = im.convert("RGB")
        q = max(50, min(95, DISCORD_JPEG_QUALITY))

        for _ in range(8):
            rgb.save(out_path, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)
            if os.path.getsize(out_path) <= max_bytes:
                return out_path, "image/jpeg"
            q -= 7
            if q < 50:
                break

        # 最後の手段。画素を少し落とす。
        while os.path.getsize(out_path) > max_bytes and rgb.width > 1200:
            new_w = int(rgb.width * 0.85)
            new_h = max(1, int(rgb.height * (new_w / rgb.width)))
            rgb = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)
            rgb.save(out_path, format="JPEG", quality=72, optimize=True, progressive=True, subsampling=0)

    return out_path, "image/jpeg"



def make_discord_thumbnail(
    src_path: str,
    *,
    caption_text: Optional[str] = None,
    baked_caption_font_size: int = 52,
    thumb_caption_font_size: int = 22,
) -> Tuple[str, str]:
    """
    4・5枚目用の確認サムネイルを作る。
    本体の高解像度PNGはR2 URLで開くため、Discord添付は軽量JPEGにする。

    caption_text指定時: 元画像の下端に焼き込み済みの出典キャプション帯は、
    サムネイルへ縮小すると文字が潰れて読めなくなる(12000px級の原寸フォントの
    まま10分の1近くに縮小されるため)。そのため焼き込み済みの帯はいったん
    取り除き、縮小後のサムネイル解像度に合わせた読めるサイズで描き直す。
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    thumb_dir = os.path.join(OUTPUT_DIR, "_discord_thumb")
    os.makedirs(thumb_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(src_path))[0]
    out_path = os.path.join(thumb_dir, f"{stem}_thumb.jpg")

    with Image.open(src_path) as im:
        rgb = im.convert("RGB")

        if caption_text:
            font = _load_caption_font(baked_caption_font_size)
            tmp = Image.new("RGB", (10, 10), "white")
            bbox = ImageDraw.Draw(tmp).textbbox((0, 0), caption_text, font=font)
            baked_bar_h = (bbox[3] - bbox[1]) + 24 * 2
            if 0 < baked_bar_h < rgb.height:
                rgb = rgb.crop((0, 0, rgb.width, rgb.height - baked_bar_h))

        w, h = rgb.size
        max_w = max(480, DISCORD_THUMB_MAX_WIDTH)
        if w > max_w:
            new_h = max(1, int(h * (max_w / w)))
            rgb = rgb.resize((max_w, new_h), Image.Resampling.LANCZOS)

        q = max(50, min(92, DISCORD_THUMB_JPEG_QUALITY))
        # サムネイルは必ず軽くする。本文のR2 URLから本体PNGを開く。
        target_mb = max(1.0, DISCORD_MAX_UPLOAD_MB * 0.5)

        for _ in range(7):
            test_img = rgb
            if caption_text:
                test_img = append_caption_bar(rgb, caption_text, font_size=thumb_caption_font_size, pad=10)
            test_img.save(out_path, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)
            size_mb = os.path.getsize(out_path) / (1024 * 1024)
            if size_mb <= target_mb:
                break

            q = max(50, q - 8)
            if rgb.width > 900:
                new_w = int(rgb.width * 0.82)
                new_h = max(1, int(rgb.height * (new_w / rgb.width)))
                rgb = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return out_path, "image/jpeg"



DISCORD_LINKS = [
    ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
    ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
    ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
    ("秋田地方気象台", "https://www.jma-net.go.jp/akita/"),
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


JMA_WEATHER_MAP_LIST_URL = "https://www.jma.go.jp/bosai/weather_map/data/list.json"
JMA_WEATHER_MAP_PNG_BASE = "https://www.jma.go.jp/bosai/weather_map/data/png"


def fetch_jma_near_monochrome_latest(key: str, label: str = "") -> Optional[Image.Image]:
    """
    気象庁の「日本周辺・白黒」天気図(list.json の near_monochrome)から最新のPNGを取得する。
      key: 'now'(実況=ASAS相当) / 'ft24'(24時間予想=FSAS24相当) / 'ft48'(48時間予想=FSAS48相当)
    ファイル名はタイムスタンプ入りで毎回変わるため、list.jsonで最新ファイル名を都度確認する。
    """
    try:
        r = requests.get(JMA_WEATHER_MAP_LIST_URL, timeout=30)
        r.raise_for_status()
        data = r.json()
        filenames = data.get("near_monochrome", {}).get(key, [])
        if not filenames:
            print(f"[NG] JMA weather_map list: no entries for near_monochrome.{key}")
            return None
        filename = filenames[-1]
    except Exception as e:
        print(f"[ERR] JMA weather_map list.json: {e}")
        return None

    url = f"{JMA_WEATHER_MAP_PNG_BASE}/{filename}"
    return fetch_jma_direct_png(url, label or key)


def fetch_jma_direct_png(url: str, label: str = "") -> Optional[Image.Image]:
    """認証不要の気象庁URLからPNG画像を直接取得してPIL Imageで返す。"""
    content = fetch_image_content(url)
    if content is None:
        print(f"[NG] JMA direct PNG {label}: fetch failed URL={url}")
        return None
    try:
        img = Image.open(io.BytesIO(content)).convert("RGB")
        print(f"[OK] JMA direct PNG {label}: size={img.size} URL={url}")
        return img
    except Exception as e:
        print(f"[ERR] JMA direct PNG {label}: {e}")
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



def combine_vertical(images: List[Image.Image], *, gap: int = 0, halign: str = "center") -> Optional[Image.Image]:
    valid = [im.convert("RGB") for im in images if im is not None]
    if not valid:
        return None

    w = max(im.width for im in valid)
    h = sum(im.height for im in valid) + gap * (len(valid) - 1)

    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for im in valid:
        x = 0 if halign == "left" else (w - im.width) // 2
        canvas.paste(im, (x, y))
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


def visual_gap_positions(
    images: List[Image.Image],
    *,
    visual_gap: int,
    measure_images: Optional[List[Image.Image]] = None,
) -> List[int]:
    """
    各画像の内蔵している白余白の量を測り、実際の絵柄(非白領域)同士の間隔が
    常にvisual_gapになるような貼り付けx座標のリストを返す(先頭は必ず0)。
    measure_imagesを渡すと、余白の測定にはそちら(例えば1段目を除いた範囲)を
    使い、実際に動かす対象はimages(全体)のままにできる。
    負の重なりが隣列の絵柄そのものに食い込まないよう、重なりは相手側の
    白余白の範囲内に収まるようクランプする(その場合、実際の間隔は
    visual_gapより広くなることがある)。
    """
    measure = measure_images if measure_images is not None else images
    bboxes = [content_bbox(im) for im in measure]
    x_positions = [0]
    for i in range(1, len(images)):
        prev_img, prev_bbox = measure[i - 1], bboxes[i - 1]
        this_bbox = bboxes[i]
        prev_right_margin = prev_img.width - 1 - prev_bbox[2]
        this_left_margin = this_bbox[0]
        raw_gap = visual_gap - prev_right_margin - this_left_margin
        raw_gap = max(raw_gap, -prev_right_margin)
        x_positions.append(x_positions[-1] + images[i - 1].width + raw_gap)
    min_x = min(x_positions)
    if min_x < 0:
        x_positions = [x - min_x for x in x_positions]
    return x_positions


def resize_to_width(img: Image.Image, target_w: int) -> Image.Image:
    """縦横比を保ったまま、指定幅に合わせる。"""
    img = img.convert("RGB")
    if target_w <= 0 or img.width <= 0:
        return img
    target_h = max(1, int(img.height * (target_w / img.width)))
    return img.resize((target_w, target_h), Image.LANCZOS)


def fit_to_cell(
    img: Image.Image,
    cell_w: int,
    cell_h: int,
    *,
    valign: str = "center",
    halign: str = "center",
) -> Image.Image:
    """
    画像を指定セル内に収め、白背景セルに配置する。
    縦横比は維持する。
    上段ASAS/FSAS24/FSAS48の端をそろえるため、固定セルを返す。
    """
    img = img.convert("RGB")

    if img.width <= 0 or img.height <= 0:
        return Image.new("RGB", (cell_w, cell_h), "white")

    scale = min(cell_w / img.width, cell_h / img.height)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (cell_w, cell_h), "white")
    if halign == "left":
        x = 0
    elif halign == "right":
        x = cell_w - new_w
    else:
        x = (cell_w - new_w) // 2
    if valign == "top":
        y = 0
    elif valign == "bottom":
        y = cell_h - new_h
    else:
        y = (cell_h - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


def fill_cell(
    img: Image.Image, cell_w: int, cell_h: int, *, valign: str = "top", halign: str = "center"
) -> Image.Image:
    """
    画像を指定セルいっぱいに拡大し、はみ出た分は切り取る(白余白を残さない)。
    縦横比は維持する(歪めない)。
    """
    img = img.convert("RGB")
    if img.width <= 0 or img.height <= 0:
        return Image.new("RGB", (cell_w, cell_h), "white")

    scale = max(cell_w / img.width, cell_h / img.height)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    if halign == "left":
        x = 0
    elif halign == "right":
        x = new_w - cell_w
    else:
        x = (new_w - cell_w) // 2
    if valign == "top":
        y = 0
    elif valign == "bottom":
        y = new_h - cell_h
    else:
        y = (new_h - cell_h) // 2
    return resized.crop((x, y, x + cell_w, y + cell_h))


def find_content_top(img: Image.Image, *, threshold: int = 245, step: int = 3) -> int:
    """画像の上端から最初に白でない行が現れるyを返す(全て白ならheight)。"""
    img = img.convert("RGB")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return y
    return h


def resize_to_width_top(img: Image.Image, target_w: int) -> Image.Image:
    """縦横比を保ったまま指定幅まで拡大・縮小する。"""
    img = img.convert("RGB")
    if target_w <= 0 or img.width <= 0:
        return img
    target_h = max(1, int(img.height * (target_w / img.width)))
    return img.resize((target_w, target_h), Image.LANCZOS)


def content_bbox(img: Image.Image, *, threshold: int = 245) -> tuple:
    """画像内の非白領域のバウンディングボックス(left, top, right, bottom)を返す(切り取りはしない)。"""
    img = img.convert("RGB")
    px = img.load()
    w, h = img.size

    left, right = 0, w - 1
    top, bottom = 0, h - 1

    def row_has_content(y: int) -> bool:
        for x in range(w):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    def col_has_content(x: int) -> bool:
        for y in range(h):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    while top < h and not row_has_content(top):
        top += 1
    while bottom >= 0 and not row_has_content(bottom):
        bottom -= 1
    while left < w and not col_has_content(left):
        left += 1
    while right >= 0 and not col_has_content(right):
        right -= 1

    if left > right or top > bottom:
        return 0, 0, w - 1, h - 1
    return left, top, right, bottom


def trim_white_margins(img: Image.Image, *, threshold: int = 245, pad: int = 0) -> Image.Image:
    """画像外周の白余白をできるだけ取り除く。"""
    img = img.convert("RGB")
    px = img.load()
    w, h = img.size

    left, right = 0, w - 1
    top, bottom = 0, h - 1

    def row_has_content(y: int) -> bool:
        for x in range(w):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    def col_has_content(x: int) -> bool:
        for y in range(h):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    while top < h and not row_has_content(top):
        top += 1
    while bottom >= 0 and not row_has_content(bottom):
        bottom -= 1
    while left < w and not col_has_content(left):
        left += 1
    while right >= 0 and not col_has_content(right):
        right -= 1

    if left > right or top > bottom:
        return img

    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w - 1, right + pad)
    bottom = min(h - 1, bottom + pad)

    return img.crop((left, top, right + 1, bottom + 1))


def trim_bottom_whitespace(img: Image.Image, *, threshold: int = 245, bottom_pad: int = 56) -> Image.Image:
    """
    下側の白余白だけを安全に少し詰める。
    上側・左右のレイアウトは維持しつつ、最下部だけを控えめにトリムする。
    """
    img = img.convert("RGB")
    px = img.load()
    w, h = img.size

    bottom = h - 1

    def row_has_content(y: int) -> bool:
        for x in range(w):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    while bottom >= 0 and not row_has_content(bottom):
        bottom -= 1

    if bottom < 0:
        return img

    new_bottom = min(h - 1, bottom + max(0, bottom_pad))
    if new_bottom >= h - 1:
        return img

    return img.crop((0, 0, w, new_bottom + 1))


def trim_right_whitespace(img: Image.Image, *, threshold: int = 245, right_pad: int = 20) -> Image.Image:
    """
    右側の白余白だけを安全に少し詰める(最右列がT72等、幅の狭いパネルの場合に
    セル内の余白がそのままキャンバス右端の余白になってしまうのを防ぐ)。
    上側・下側・左側のレイアウトは維持しつつ、最右列だけを控えめにトリムする。
    """
    img = img.convert("RGB")
    px = img.load()
    w, h = img.size

    right = w - 1

    def col_has_content(x: int) -> bool:
        for y in range(h):
            r, g, b = px[x, y]
            if r < threshold or g < threshold or b < threshold:
                return True
        return False

    while right >= 0 and not col_has_content(right):
        right -= 1

    if right < 0:
        return img

    new_right = min(w - 1, right + max(0, right_pad))
    if new_right >= w - 1:
        return img

    return img.crop((0, 0, new_right + 1, h))


CAPTION_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # ubuntu apt
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",  # macOS
    "/Library/Fonts/Arial Unicode.ttf",
]


def _load_caption_font(size: int) -> ImageFont.ImageFont:
    for path in CAPTION_FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_caption_lines(text: str, font, available_w: int, tmp_draw) -> List[str]:
    """
    "　"区切りの単位で、収まる範囲まで貪欲に行を詰める(文字単位ではなく
    意味のまとまり単位で改行するため読みやすい)。1単位だけでも収まらない
    場合はその行だけ突き出る(呼び出し側で最終的にフォントを縮めて対応)。
    """
    segments = text.split("　")
    lines: List[str] = []
    current = ""
    for seg in segments:
        candidate = seg if not current else current + "　" + seg
        w = tmp_draw.textbbox((0, 0), candidate, font=font)[2]
        if w <= available_w or not current:
            current = candidate
        else:
            lines.append(current)
            current = seg
    if current:
        lines.append(current)
    return lines


def append_caption_bar(
    img: Image.Image,
    text: str,
    *,
    font_size: int = 52,
    pad: int = 24,
    align: str = "right",
    min_font_size: int = 16,
) -> Image.Image:
    """
    画像の下に、出典・作成日時を記した余白バーを追加する(既定で右寄せ)。
    横幅が足りない場合(サムネイル等)は、まず意味のまとまり単位で複数行に
    折り返す。それでも収まらない極端に狭い場合だけ、可読性を保てる
    min_font_size を下限にフォントを縮小する(文字が潰れて読めなくなる
    ほどには縮めない)。
    """
    img = img.convert("RGB")
    tmp = Image.new("RGB", (10, 10), "white")
    draw_tmp = ImageDraw.Draw(tmp)
    available_w = max(1, img.width - pad * 2)

    size = font_size
    while True:
        font = _load_caption_font(size)
        single_bbox = draw_tmp.textbbox((0, 0), text, font=font)
        if (single_bbox[2] - single_bbox[0]) <= available_w:
            lines = [text]
            break
        lines = _wrap_caption_lines(text, font, available_w, draw_tmp)
        widest = max(draw_tmp.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        if widest <= available_w or size <= min_font_size:
            break
        size -= 2

    line_bboxes = [draw_tmp.textbbox((0, 0), ln, font=font) for ln in lines]
    line_h = max(b[3] - b[1] for b in line_bboxes)
    line_gap = max(2, line_h // 6)
    bar_h = line_h * len(lines) + line_gap * (len(lines) - 1) + pad * 2

    bar = Image.new("RGB", (img.width, bar_h), "white")
    draw = ImageDraw.Draw(bar)
    y = pad
    for ln, bbox in zip(lines, line_bboxes):
        w = bbox[2] - bbox[0]
        x = (img.width - pad - w) if align == "right" else pad
        draw.text((x, y - bbox[1]), ln, fill=(90, 90, 90), font=font)
        y += line_h + line_gap

    canvas = Image.new("RGB", (img.width, img.height + bar_h), "white")
    canvas.paste(img, (0, 0))
    canvas.paste(bar, (0, img.height))
    return canvas


def jma_source_caption() -> str:
    return (
        "出典：気象庁　https://www.jma.go.jp/jma/kishou/know/expert/"
        "　提供資料を合成編集　作成：177chart"
    )


def prepare_comp_panel(img: Image.Image, target_w: int) -> Image.Image:
    """
    COMP12/36/72の外周余白を整理してから、上段セル幅いっぱいまで拡大する。
    2段目を1.5倍程度に見せ、画像の端を上段3枚の端とそろえる。
    """
    trimmed = trim_white_margins(img, pad=LAYOUT5_TRIM_PAD)
    return resize_to_width_top(trimmed, target_w)


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
    FXJP854 は「1ページ目を上下に切断 → 左右に横並び」で作る。

    調整方針:
    - 上下分割した各画像は外周の白余白をできるだけ除去する。
    - 横並び後も上下の白余白をできるだけ除去する。
    - target_h が指定された場合でも縦中央には置かず、上揃えで配置する。
      これにより、2段目との間の無駄な余白をなくし、左列3段目とも上端をそろえやすくする。
    """
    if not pages:
        return None

    img = pages[0].convert("RGB")
    w, h = img.size
    mid_y = h // 2

    upper = img.crop((0, 0, w, mid_y))
    lower = img.crop((0, mid_y, w, h))

    # それぞれの白余白を削ってから横並びにする
    upper = trim_white_margins(upper, pad=0)
    lower = trim_white_margins(lower, pad=0)

    joined = combine_horizontal([upper, lower], gap=gap, valign="top")
    if joined is None:
        return None

    # 横結合後も上下左右の白余白を削る
    joined = trim_white_margins(joined, pad=0)

    # 幅の目標がある場合は、縮小だけでなく拡大も許可する。
    # これにより、下段FXJP854を「3段目の左右端の中央どうし」の間に広げられる。
    if target_w and joined.width != target_w:
        joined = resize_to_width_top(joined, target_w)

    # 高さ上限がある場合のみ、必要に応じて縮小する。
    if target_h and joined.height > target_h:
        new_w = max(1, int(joined.width * (target_h / joined.height)))
        joined = joined.resize((new_w, target_h), Image.LANCZOS)

    # 高さ指定があるときは、上揃えのまま必要最小限のキャンバスに載せる。
    if target_h:
        canvas_w = joined.width
        canvas_h = max(target_h, joined.height)
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        canvas.paste(joined, (0, 0))
        return canvas

    return joined


# =============================================================================
# 予報図 レイアウト構築
# =============================================================================

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


def build_layout4_jma_direct(errors: List[str]) -> Optional[Attachment]:
    """
    週間4列結合の気象庁直接取得版。WCN（Weathercaster.jp）には一切アクセスしない。
      1列目: SKAISETU（週間予報解説資料、JMA直取得PDF）
      2列目: FEFE19（気象庁公開PNG）
      3列目: FXXN519（気象庁公開PNG）
      4列目: FZCX50（気象庁公開PNG）
    """
    print("-> Building Layout 4 (Weekly Multicolumn, JMA-direct)")

    skai_pages = fetch_jma_direct_pdf_pages(JMA_SKAISETU_URL, "SKAISETU")
    col1_img = combine_vertical(skai_pages, gap=LAYOUT_GAP) if skai_pages else None
    if col1_img is None:
        errors.append("Layout4JMA: SKAISETU download/conversion failed")

    col2_img = fetch_jma_direct_png(JMA_FEFE19_URL, "FEFE19")
    col3_img = fetch_jma_direct_png(JMA_FXXN519_URL, "FXXN519")
    col4_img = fetch_jma_direct_png(JMA_FZCX50_URL, "FZCX50")

    if col2_img is None:
        errors.append("Layout4JMA: FEFE19 failed")
    if col3_img is None:
        errors.append("Layout4JMA: FXXN519 failed")
    if col4_img is None:
        errors.append("Layout4JMA: FZCX50 failed")

    canvas = combine_horizontal([col1_img, col2_img, col3_img, col4_img], gap=LAYOUT_GAP, valign="top")
    if canvas is None:
        return None

    caption = jma_source_caption()
    canvas = append_caption_bar(canvas, caption)

    return pil_to_attachment(canvas, "LAYOUT_4_WEEKLY")


def build_layout_5(session: requests.Session, errors: List[str]) -> Optional[Attachment]:
    """
    ⑤ 全部入り（TeamSABOTENスタイル・タブレット天気図完全再現版）
      左列: TKAISETU(JMA直) / AUPQ35(JMA) / AUPQ78(JMA)
      上段: ASAS / FSAS24 / FSAS48
      中段: COMP12 / COMP36 / COMP72
      下段: FXJP854（上下分割→横並び）
    """
    print("-> Building Layout 5 (Perfect Dashboard Layout)")

    issue_dt_jst = issue_base_jst()
    cycle = jma_cycle_suffix(issue_dt_jst)
    print(f"[INFO] Layout5 JMA numeric cycle: {cycle}")

    # 1. 各パーツの読み込み
    # TKAISETU: JMA直取得（kaisetsu_tanki_latest.pdf = 最新版）。
    # WCN経由は朝03:40版で貼り付くことがあるため、03:40/15:40の最新へ追従するJMA公開URLを使う。
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
    # 3. 右側3列の共通セル幅を決める
    #    上段 ASAS/FSAS24/FSAS48 と
    #    中段 COMP12/COMP36/COMP72 の横幅を完全にそろえる
    # -------------------------------------------------------------------------
    top_parts = [asas, fsas24, fsas48]
    mid_parts = [comp12, comp36, comp72]

    top_widths = [p.width for p in top_parts if p is not None]
    mid_widths = [p.width for p in mid_parts if p is not None]

    # 基本は上段の幅を基準にする。
    # ただし中段にもっと大きい画像がある場合も崩れないよう max にする。
    right_col_w = max(top_widths + mid_widths) if (top_widths or mid_widths) else 1200

    # 右側全体の幅。上段・中段・下段すべてこの幅に合わせる。
    right_w = right_col_w * 3 + LAYOUT_GAP * 2

    print(f"[INFO] Layout5 right_col_w={right_col_w}, right_w={right_w}")

    # -------------------------------------------------------------------------
    # 4. 右側・上段（ASAS / FSAS24 / FSAS48）
    #    3列固定セルで横並び
    # -------------------------------------------------------------------------
    top_cells: List[Image.Image] = []
    for p in top_parts:
        if p is not None:
            top_cells.append(fit_to_cell(p, right_col_w, row1_h, valign="top"))
        else:
            top_cells.append(Image.new("RGB", (right_col_w, row1_h), "white"))

    top_canvas = combine_horizontal(top_cells, gap=LAYOUT_GAP, valign="top")

    # -------------------------------------------------------------------------
    # 5. 右側・中段（COMP12 / COMP36 / COMP72）
    #    各画像を right_col_w いっぱいまで拡大して、画像の左右端を上段とそろえる。
    #    高さは row2_h に押し込めず、実画像の高さを活かす。
    # -------------------------------------------------------------------------
    mid_cells: List[Image.Image] = []
    for p in mid_parts:
        if p is not None:
            mid_cells.append(prepare_comp_panel(p, right_col_w))
        else:
            mid_cells.append(Image.new("RGB", (right_col_w, row2_h), "white"))

    mid_canvas = combine_horizontal(mid_cells, gap=LAYOUT_GAP, valign="top")

    # -------------------------------------------------------------------------
    # 6. FXJP854 を右側3列幅に合わせて組み立てる
    # -------------------------------------------------------------------------
    if fxjp854_raw:
        # FXJP854は「上下切断→横並び」。
        # 希望位置:
        #   左端  = 3段目の1枚目と2枚目の中央
        #   右端  = 3段目の5枚目と6枚目の中央
        # に合わせる。
        # 1枚目と2枚目の中央 〜 5枚目と6枚目の中央 に合わせる。
        # 3つのCOMPパネルで見れば「左パネル中央 〜 右パネル中央」に相当するため、
        # 幅は厳密に right_w - right_col_w とする。
        fx_target_w = max(1, int(right_w - right_col_w))
        print(f"[INFO] Layout5 FX target width exact: {fx_target_w} (right_w={right_w}, right_col_w={right_col_w})")
        fxjp854 = process_fxjp854_fit(
            fxjp854_raw,
            fx_target_w,
            target_h=None,
            gap=LAYOUT_GAP,
        )
    else:
        errors.append("Layout5: FXJP854 missing")
        fxjp854 = None

    if fxjp854 is None:
        fxjp854 = Image.new("RGB", (right_w, row3_h), "white")

    # -------------------------------------------------------------------------
    # 7. 左列3段目と FXJP854 の高さを最終同期し、左列を縦結合
    # -------------------------------------------------------------------------
    final_row3_h = max(left_row3.height, fxjp854.height)
    if left_row3.height != final_row3_h:
        left_row3 = pad_to_height(left_row3, final_row3_h)
    if fxjp854.height != final_row3_h:
        fxjp854 = pad_to_height(fxjp854, final_row3_h)

    left_canvas = combine_vertical([left_row1, left_row2, left_row3], gap=LAYOUT_GAP)

    # -------------------------------------------------------------------------
    # 8. 右側ブロックを縦結合（中央揃えで貼り付け）
    # -------------------------------------------------------------------------
    # 上段→中段の間だけ通常ギャップを入れ、中段→下段(FXJP854)は密着させる。
    rows_with_gap = [
        (top_canvas, LAYOUT_GAP),
        (mid_canvas, 0),
        (fxjp854, 0),
    ]
    valid_rows = [(row, gap_after) for row, gap_after in rows_with_gap if row is not None]
    right_h = sum(row.height + gap_after for row, gap_after in valid_rows)
    if valid_rows:
        right_h -= valid_rows[-1][1]
    right_canvas = Image.new("RGB", (right_w, right_h), "white")

    y = 0
    for row, gap_after in valid_rows:
        x = (right_w - row.width) // 2
        right_canvas.paste(row, (x, y))
        y += row.height + gap_after

    # -------------------------------------------------------------------------
    # 9. 左列と右側ブロックの最終マージ
    # -------------------------------------------------------------------------
    if left_canvas is None:
        right_canvas = trim_bottom_whitespace(right_canvas, bottom_pad=56)
        return pil_to_attachment(right_canvas, "LAYOUT_5_DASHBOARD")

    final_w = left_canvas.width + LAYOUT_GAP + right_canvas.width
    final_h = max(left_canvas.height, right_canvas.height)

    final_canvas = Image.new("RGB", (final_w, final_h), "white")
    final_canvas.paste(left_canvas, (0, 0))
    final_canvas.paste(right_canvas, (left_canvas.width + LAYOUT_GAP, 0))

    # 下側だけ安全に少し詰める。上側・左右のレイアウトは崩さない。
    final_canvas = trim_bottom_whitespace(final_canvas, bottom_pad=56)

    return pil_to_attachment(final_canvas, "LAYOUT_5_DASHBOARD")


# ASAS等の広域チャートから日本付近だけを切り出す範囲（幅・高さに対する割合）。
# ASAS_MONO.pdf (3640x2573) で目視確認して決めた値。
JAPAN_CROP_FRACTIONS = (0.30, 0.22, 0.56, 0.58)  # (x0, y0, x1, y1)

# 同じくASAS_MONO.pdfから、FXFE5782(T12/24, 500/850hPa)と同程度の
# 極東アジア広域を切り出す範囲。目視確認して決めた値。
ASIA_CROP_FRACTIONS = (0.22, 0.10, 0.75, 0.70)  # (x0, y0, x1, y1)


def crop_japan_area(img: Image.Image) -> Image.Image:
    """広域天気図から日本付近だけを切り出す。"""
    img = img.convert("RGB")
    w, h = img.size
    x0, y0, x1, y1 = JAPAN_CROP_FRACTIONS
    return img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))


def crop_asia_area(img: Image.Image) -> Image.Image:
    """広域天気図から極東アジア(中国大陸〜日本〜日付変更線付近)を切り出す。"""
    img = img.convert("RGB")
    w, h = img.size
    x0, y0, x1, y1 = ASIA_CROP_FRACTIONS
    return img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))


def split_top_bottom(img: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """画像を上半分・下半分に2分割する。AXFE578やFXJP854のように
    1ページに複数時刻/複数気圧面がまとまっている図に使う。"""
    img = img.convert("RGB")
    half_h = img.height // 2
    return img.crop((0, 0, img.width, half_h)), img.crop((0, half_h, img.width, img.height))


def resize_to_height(img: Image.Image, target_h: int) -> Image.Image:
    img = img.convert("RGB")
    if target_h <= 0 or img.height <= 0:
        return img
    target_w = max(1, int(img.width * (target_h / img.height)))
    return img.resize((target_w, target_h), Image.LANCZOS)


def build_layout_dashboard_jma(errors: List[str]) -> Optional[Attachment]:
    """
    有料DM配信用「全部入り」の気象庁直接取得版。
    WCN（Weathercaster.jp会員ページ）を一切経由せず、気象庁が自ら公開している
    データだけで、実際のWCN版「全部入り」と同じ構成を再現する。

    左端の縦長列: (一段目は空白) / AXJP140 / AXJP130 / 短期予報解説情報(TKAISETU、大きめ・下揃え)
    2列目: AUPA20(一段目) / AUPQ35(全体) / AUPQ78(全体)
    3列目: ASAS(一段目、日本周辺白黒) / AXFE578上段(500hPa) / ASAS(極東アジア切り出し) / AUPQ35下段 / AXFE578下段(850hPa)
    4列目: FSAS24(一段目、24時間後) / FXFE502(12-24h) / FXFE5782(12-24h) / FXJP854上半分(T=12,24)
    5列目: FSAS48(一段目、48時間後) / FXFE504(36-48h) / FXFE5784(36-48h) / FXJP854下半分(T=36,48)
    6列目: (一段目は空白) / FXFE507(72h) / FXFE577(72h)  ※FXJP854はT=48までのためT72列には無し
    """
    print("-> Building JMA-direct Dashboard (DM用)")

    issue_dt_jst = issue_base_jst()
    cycle = jma_cycle_suffix(issue_dt_jst)

    # ---- 素材取得 ----
    tkai = get_first_page_or_none(fetch_jma_direct_pdf_pages(JMA_TKAISETU_URL, "TKAISETU"))
    if tkai is not None:
        # TKAISETUはPDFページ自体の右側に大きな白余白があり、そのままだと
        # 隣列との間に不要な隙間ができるのであらかじめ切り詰める。
        tkai = trim_white_margins(tkai, pad=20)

    # 一段目(row1): ASAS(日本周辺白黒版のみ) / FSAS24 / FSAS48。気象庁の
    # 「日本周辺・白黒」天気図(list.jsonの near_monochrome、あらかじめ日本付近に
    # 切り出し済み)から取得する。ASASの広域版は列3の3段目(極東アジア切り出し)に
    # 既に出ているため一段目には出さないが、日本周辺白黒版は別物なので出す。
    asas_new = fetch_jma_near_monochrome_latest("now", "ASAS")
    fsas24_new = fetch_jma_near_monochrome_latest("ft24", "FSAS24")
    fsas48_new = fetch_jma_near_monochrome_latest("ft48", "FSAS48")
    for name, im in (("ASAS", asas_new), ("FSAS24", fsas24_new), ("FSAS48", fsas48_new)):
        if im is None:
            errors.append(f"DashboardJMA: {name} missing")

    # 一段目にはさらに、広域版のASAS/FSAS24/FSAS48も並べる(日本周辺白黒版とは別の
    # 材料として両方使う)。3列目のASAS切り出し(極東アジア広域)にもASAS広域版を使う。
    asas_wide = get_first_page_or_none(fetch_jma_direct_pdf_pages(JMA_ASAS_MONO_URL, "ASAS_WIDE"))
    fsas24_wide = get_first_page_or_none(fetch_jma_direct_pdf_pages(JMA_FSAS24_MONO_URL, "FSAS24_WIDE"))
    fsas48_wide = get_first_page_or_none(fetch_jma_direct_pdf_pages(JMA_FSAS48_MONO_URL, "FSAS48_WIDE"))
    for name, im in (("ASAS(wide)", asas_wide), ("FSAS24(wide)", fsas24_wide), ("FSAS48(wide)", fsas48_wide)):
        if im is None:
            errors.append(f"DashboardJMA: {name} missing")

    # AXJP140は1ページにALONG 140E(上)とALONG 130E(下)の2断面図が
    # 縦に並んでいるので、上下分割してAXJP140/AXJP130として別々に使う。
    # 気象庁からは1枚のPDFとして配信されており、軸ラベル・観測点名など周囲の
    # 文字情報を含めて外枠は一切トリミングしない。ただし外枠のさらに外側にある
    # 純粋な白余白(文字・枠線が何も無い部分)だけは削り、AUPQ78との上端合わせの
    # ズレを無くす(枠や文字は絶対に切り取らない)。
    # 左右の余白は分割前(結合ページ全体)の共通の範囲でまとめて切り詰める。
    # 140E/130Eそれぞれ個別に左右トリミングすると、切り詰め量のわずかな違いで
    # 実効的な幅が変わり、2つの図の拡大率(=図柄の大きさ)がずれて見えてしまう
    # ため、左右は共通・上下だけ個別にトリミングする。
    axjp140_raw = get_first_page_or_none(fetch_jma_numeric_pdf_pages("axjp140", cycle))
    if axjp140_raw is None:
        errors.append("DashboardJMA: AXJP140 missing")
        axjp140, axjp130 = None, None
    else:
        left, _, right, _ = content_bbox(axjp140_raw)
        axjp140_raw_lr = axjp140_raw.crop((left, 0, right + 1, axjp140_raw.height))
        axjp140_half, axjp130_half = split_top_bottom(axjp140_raw_lr)

        def _trim_vertical_only(im: Image.Image) -> Image.Image:
            _, top, _, bottom = content_bbox(im)
            return im.crop((0, top, im.width, bottom + 1))

        axjp140 = _trim_vertical_only(axjp140_half)
        axjp130 = _trim_vertical_only(axjp130_half)

    aupa20 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("aupa20", cycle))
    if aupa20 is None:
        errors.append("DashboardJMA: AUPA20 missing")
    else:
        # AUPA20はPDFページ自体に白余白があり、そのままfill_cellすると
        # 下のAUPQ35(同じくfill_cellで余白なく詰める)より幅が狭く見えるため、
        # あらかじめ切り詰めておく。
        aupa20 = trim_white_margins(aupa20)

    aupq35 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("aupq35", cycle))
    aupq78 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("aupq78", cycle))
    if aupq35 is None:
        errors.append("DashboardJMA: AUPQ35 missing")
    else:
        # AXJP140/AXJP130/TKAISETUは既に切り詰め済みなので、AUPQ35/AUPQ78も
        # 同様に切り詰めておかないと、fill_cell後も自身の白余白が残った分だけ
        # 絵柄の開始位置がずれて見える(セルの大きさは揃っていても中の絵柄が揃わない)。
        aupq35 = trim_white_margins(aupq35)
    if aupq78 is None:
        errors.append("DashboardJMA: AUPQ78 missing")
    else:
        aupq78 = trim_white_margins(aupq78)

    axfe578 = get_first_page_or_none(fetch_jma_numeric_pdf_pages("axfe578", cycle))
    if axfe578 is None:
        errors.append("DashboardJMA: AXFE578 missing")
        axfe578_upper, axfe578_lower = None, None
    else:
        axfe578_upper, axfe578_lower = split_top_bottom(axfe578)
        # AXFE578はPDFページ自体に左と上に白余白があり、そのままだと2列目(aupq_col、
        # 既に余白なく詰めてある)と絵柄の位置がずれて見えるため、切り詰めておく。
        axfe578_upper = trim_white_margins(axfe578_upper)
        axfe578_lower = trim_white_margins(axfe578_lower)

    # ---- 列3・4・5: 各列とも、その列の地上天気図(surface)のネイティブ幅をそのまま使う ----
    # (T=72のfxfe507/fxfe577は1コマのみのPDFで、T12/24を並べたfxfe502等より幅が狭い。
    #  列ごとに幅が違ってよく、無理に他列と同じ幅に揃えると余白だらけになる)
    ref_surface = get_first_page_or_none(fetch_jma_numeric_pdf_pages("fxfe502", cycle))
    # FXJP854の幅合わせの基準として、列4(FXFE5782)・列5(FXFE5784)の絵柄部分を先に取得しておく
    # (build_period_columnの中で改めて取得されるが、ここでは絵柄の左位置・幅を測るためだけに使う)。
    fxfe5782_ref = get_first_page_or_none(fetch_jma_numeric_pdf_pages("fxfe5782", cycle))
    fxfe504_ref = get_first_page_or_none(fetch_jma_numeric_pdf_pages("fxfe504", cycle))
    fxfe5784_ref = get_first_page_or_none(fetch_jma_numeric_pdf_pages("fxfe5784", cycle))

    fxjp854_page = get_first_page_or_none(fetch_jma_numeric_pdf_pages("fxjp854", cycle))
    if fxjp854_page is None:
        errors.append("DashboardJMA: FXJP854 missing")
        fxjp854_upper, fxjp854_lower = None, None
    else:
        fxjp854_upper, fxjp854_lower = split_top_bottom(fxjp854_page)
        # FXJP854自身の白余白を切り詰めてから、列4(FXFE5782)・列5(FXFE5784)の
        # 幅いっぱいに引き伸ばす。col3/col4の各段(build_period_rows)も同じく
        # 「トリミング→列のネイティブ幅まで引き伸ばす」方式(余白ゼロで絵柄が
        # 列幅いっぱいに広がる)で作っているため、同じ方式にしないと列側は余白ゼロ・
        # FXJP854側だけ絵柄が縮こまって左右に余白が残る、という不一致が起きる。
        fxjp854_upper = trim_white_margins(fxjp854_upper)
        fxjp854_lower = trim_white_margins(fxjp854_lower)

        def fit_fxjp854_half(img: Image.Image, ref_img: Optional[Image.Image]) -> Image.Image:
            target_w = ref_img.width if ref_img is not None else (
                ref_surface.width if ref_surface is not None else img.width
            )
            return resize_to_width(img, target_w)

        # 上段(T12/24)はFXFE5782(列4)、下段(T36/48)はFXFE5784(列5)の列幅に合わせる。
        fxjp854_upper = fit_fxjp854_half(fxjp854_upper, fxfe5782_ref)
        fxjp854_lower = fit_fxjp854_half(fxjp854_lower, fxfe5784_ref)

    # 列3・4・5は同じ種類のパネル(地上天気図・上層天気図)。FXFE507/577(T72)は
    # T12/24等を並べたfxfe502等よりネイティブ幅が狭い(1コマのみのPDFのため)が、
    # 幅は無理に揃えず各列ネイティブのまま(自然な高さ)にする。

    def build_period_rows(
        surface_code: str,
        upper_code: str,
        surface_pre: Optional[Image.Image] = None,
        upper_pre: Optional[Image.Image] = None,
    ) -> List[Image.Image]:
        """
        surface(例: fxfe502)・upper(例: fxfe5782)は、それぞれ1ページの中に
        上段・下段の2種類の物理量(例: 500hPa/地上、500hPa気温/850hPa)がT=12・T=24
        などを横に並べた形で入っている。3列目(AXFE578ベース)の4段
        (500hPa/ASAS地上/AUPQ35(500hPa)/AXFE578下段(850hPa))と種類ごとに
        揃えるため、それぞれ上下に分割し、4段(自然な高さ、切り取らない)として返す。
        """
        surface = surface_pre if surface_pre is not None else get_first_page_or_none(fetch_jma_numeric_pdf_pages(surface_code, cycle))
        upper = upper_pre if upper_pre is not None else get_first_page_or_none(fetch_jma_numeric_pdf_pages(upper_code, cycle))
        if surface is None:
            errors.append(f"DashboardJMA: {surface_code} missing")
        if upper is None:
            errors.append(f"DashboardJMA: {upper_code} missing")

        rows: List[Image.Image] = []
        for im in (surface, upper):
            if im is None:
                continue
            target_w = im.width
            top, bottom = split_top_bottom(im)
            rows.append(resize_to_width(trim_white_margins(top), target_w))
            rows.append(resize_to_width(trim_white_margins(bottom), target_w))
        return rows

    # FXJP854(T12/24/36/48)は列4・列5の直下に、他列(1〜3・6列目)とは無関係な
    # 独立した「4段目」として後で別途くっつける(ここでは列に含めない)。
    # そうしないと、列4・5だけがFXJP854の分だけ高くなり、他列がそれに引きずられて
    # 余分な白余白を抱えることになる。
    col3_rows = build_period_rows("fxfe502", "fxfe5782", surface_pre=ref_surface, upper_pre=fxfe5782_ref)
    col4_rows = build_period_rows("fxfe504", "fxfe5784", surface_pre=fxfe504_ref, upper_pre=fxfe5784_ref)
    # T72はFXJP854(T=12/24/36/48のみ)に対応する時刻が無いため、FXJP854は付けない。
    col5_rows = build_period_rows("fxfe507", "fxfe577")
    # T72(col5)はfxfe507/577がfxfe502/5782等と別テンプレート(1コマのみ)のため、
    # 自然な高さのままだと段の位置が列3・列4よりわずかにずれる。列3の各段の高さに
    # 厳密に合わせる(幅は列5ネイティブのまま、fill_cellで高さだけ詰める)。
    if col3_rows:
        # fill_cellだと日によって列5側が列3より自然な高さで低い場合にキャプション文字
        # (「T=72」等)が下端で切れてしまう恐れがあるため、fit_to_cell(切り取らず
        # 縮小してレターボックス)で高さを合わせる。
        col5_rows = [
            fit_to_cell(row, row.width, col3_rows[i].height, valign="top") if i < len(col3_rows) else row
            for i, row in enumerate(col5_rows)
        ]
    col3 = combine_vertical(col3_rows, gap=LAYOUT_GAP) if col3_rows else None
    col4 = combine_vertical(col4_rows, gap=LAYOUT_GAP) if col4_rows else None
    col5 = combine_vertical(col5_rows, gap=LAYOUT_GAP) if col5_rows else None

    # ---- 「天気図1枚」の基準サイズ = 列3の地上天気図(fxfe502)のネイティブサイズ ----
    # 列2はこのサイズのセルに各コマを収める(fit_to_cellで縦横比を保ったままレターボックス)。
    # 列2を丸ごと引き伸ばす(=歪む)のではなく、コマ単位で標準サイズに揃えることで歪みを防ぐ。
    standard_w = col3.width if col3 is not None else 2798
    standard_h = ref_surface.height if ref_surface is not None else 2218

    # AUPQ列＋列2の2列を合わせて、他の列(T12など)1列分の幅に収める。
    col12_w = standard_w // 2
    col12_h = standard_h // 2

    # ---- 3列目(旧・列2、AXFE578ベース): AXFE578上段(500hPa) / ASAS(極東アジア切り出し) /
    # AUPQ35下段 / AXFE578下段(850hPa)。AUPA20はここから2列目(aupq_col)へ移動した。
    asas_asia = crop_asia_area(asas_wide) if asas_wide is not None else None
    # aupq35は既に全体を切り詰め済みだが、上下分割した境目には余白が残るので
    # 下段(500hPa)だけ改めて切り詰める。
    aupq35_lower = trim_white_margins(split_top_bottom(aupq35)[1]) if aupq35 is not None else None

    # 4段それぞれの種類が4列目(col3_rows)と対応するよう並べている:
    # 0=500hPa系(AXFE578上段 ⇔ FXFE502上段) / 1=地上系(ASAS ⇔ FXFE502下段) /
    # 2=500hPa気温系(AUPQ35下段 ⇔ FXFE5782上段) / 3=850hPa系(AXFE578下段 ⇔ FXFE5782下段)。
    # col3_rows(自然な高さ、切り取っていない)の高さに合わせてfill_cellで詰めることで、
    # 種類の合う段同士が横方向にぴったり並ぶ。
    col2_items = [axfe578_upper, asas_asia, aupq35_lower, axfe578_lower]
    col2_cells = []
    for i, im in enumerate(col2_items):
        if im is None:
            continue
        target_h = col3_rows[i].height if i < len(col3_rows) else col12_h
        cell = fill_cell(im, col12_w, target_h, valign="top")
        col2_cells.append(cell)
    col2 = combine_vertical(col2_cells, gap=LAYOUT_GAP) if col2_cells else None

    # ---- 一段目(3列目・4列目・5列目): 広域版(切り抜かず全体表示)を列の先頭に、
    # 日本周辺白黒版はそれを横に並べる(縦に重ねない)。広域版は元の縦横比の都合で
    # header_hいっぱいまで表示しても幅に余裕があるため、日本周辺白黒版もheader_h
    # いっぱいまで拡大し、周囲に空白が残らないようにする(合計幅がその列の通常幅
    # (target_w)ちょうどになるよう、広域版側の割り当て幅だけを削る)。
    # 6列目(T72)の上は空白のまま。
    header_h = col12_h
    NEAR_MONO_BADGE_SCALE = 1.0  # header_hに対する高さの比率(いっぱいまで拡大し余白をなくす)。

    def prepend_header_pair(
        col: Optional[Image.Image],
        wide_img: Optional[Image.Image],
        near_img: Optional[Image.Image],
    ) -> Optional[Image.Image]:
        if col is None:
            return None
        target_w = col.width
        # 広域版(ASAS_MONO等)はPDF自体に左右の白余白があり、そのままだと
        # halign="left"で揃えても絵柄の左端がFXFE502/FXJP854のT12側と揃わない。
        # 先に切り詰めておく(観測点名等の枠は無いシンプルな広域図なので、
        # AXJP140等と違って全体をそのまま切り詰めて問題ない)。
        wide_img = trim_white_margins(wide_img) if wide_img is not None else None

        # 日本周辺白黒版はすべて同じサイズ(header_h×NEAR_MONO_BADGE_SCALE)に揃える。
        # 広域版と並ぶ場合はその分だけ広域版を小さくし、単独の場合もこれより大きくしない。
        badge_cell = (
            resize_to_height(near_img, max(1, int(header_h * NEAR_MONO_BADGE_SCALE)))
            if near_img is not None
            else None
        )
        badge_w = badge_cell.width if badge_cell is not None else 0

        # ヘッダーは常にheader_hちょうどの高さの白キャンバスにする(広域版が無い列でも
        # header_hを下回らないようにし、本体(axfe578等)の開始位置が他列とずれないようにする)。
        # 日本周辺白黒版バッジは、広域版(またはヘッダー枠)の下端に揃える(下揃え)。
        header = Image.new("RGB", (target_w, header_h), "white")
        x = 0
        if wide_img is not None:
            wide_target_w = max(1, target_w - badge_w)
            # halign="left"でスロット内の中央寄せをやめ、絵柄の左端をスロットの
            # 左端(=列の左端、FXFE502のT12側・FXJP854のT12側と共通)にきっちり揃える。
            wide_cell = fit_to_cell(wide_img, wide_target_w, header_h, valign="top", halign="left")
            header.paste(wide_cell, (0, 0))
            x = wide_cell.width
        if badge_cell is not None:
            # 広域版が無い列(バッジ単独)は、列(本体)の幅の中央に配置する。
            badge_x = x if wide_img is not None else max(0, (target_w - badge_w) // 2)
            header.paste(badge_cell.convert("RGB"), (badge_x, header_h - badge_cell.height))

        return combine_vertical([header, col], gap=LAYOUT_GAP, halign="left")

    # ASAS広域版は列3の3段目(極東アジア切り出し)に既にあるため一段目には出さないが、
    # 日本周辺白黒版は別物なので一段目に残す。
    col2 = prepend_header_pair(col2, None, asas_new)
    col3 = prepend_header_pair(col3, fsas24_wide, fsas24_new)
    col4 = prepend_header_pair(col4, fsas48_wide, fsas48_new)
    col5 = prepend_header_pair(col5, None, None)

    # 短期予報解説資料(TKAISETU)・AXJP140・AXJP130はいずれも気象庁配信のPDFページ
    # そのままの外枠(タイトル・軸ラベル・観測点表など)を欠かさず見せたいので、
    # fill_cell(クロップして詰める)ではなく、縦横比を保ったまま拡大縮小するだけ
    # (切り取らない)。TKAISETUの上端がAUPQ35(300hPa)の上端、下端がAUPQ35(500hPa)
    # の下端に、AXJP140の上端がAUPQ78(700hPa)の上端に、AXJP130の下端がAUPQ78
    # (850hPa)の下端にそれぞれ揃うよう、col3_rows(段の高さ)から算出した高さに
    # 合わせて拡大する(resize_to_height、切り取りなし)。
    tkai_target_h = (
        col3_rows[0].height + LAYOUT_GAP + col3_rows[1].height if len(col3_rows) > 1 else col12_h
    )
    axjp130_target_h = col3_rows[3].height if len(col3_rows) > 3 else col12_h
    tkai_natural = resize_to_height(tkai, tkai_target_h) if tkai is not None else None
    axjp130_natural = resize_to_height(axjp130, axjp130_target_h) if axjp130 is not None else None
    # AXJP140は140E/130Eの図柄の大きさ(拡大率)がAXJP130と揃うよう、AXJP130と
    # 同じ縮尺(scale)で拡大する(col3_rows[2]には個別に合わせない)。
    # 左右トリミングを共通化済み(幅が同じ)なので、縮尺を揃えれば図柄の大きさも揃う。
    if axjp140 is not None and axjp130 is not None and axjp130.height > 0:
        axjp140_scale = axjp130_target_h / axjp130.height
        axjp140_natural = axjp140.resize(
            (max(1, round(axjp140.width * axjp140_scale)), max(1, round(axjp140.height * axjp140_scale))),
            Image.LANCZOS,
        )
    else:
        axjp140_natural = None

    # ---- 2列目(aupq_col): ヘッダー相当=AUPA20 / 本体=AUPQ35(500hPa・300hPa) / AUPQ78(700hPa・850hPa)。
    # 「同じ場所が時間経過でどう変わるか」を横に並べて見せるのが目的なので、
    # 緯度が横一直線に揃うことを優先し、3列目(col3_rows)と同じ段位置に並べ替える:
    # 段0=AUPQ35下段(500hPa)⇔col3_rows[0](FXFE502上段、500hPa)、段3=AUPQ78下段(850hPa)
    # ⇔col3_rows[3](FXFE5782下段、850hPa)。対応する段の無いAUPQ35上段(300hPa)・
    # AUPQ78上段(700hPa)は段1・段2の位置を借りる(意味は異なるが位置だけ揃える)。
    #
    # AXFE578/FXFE502は緯度40度線がそれぞれの絵柄の高さに対しておよそ36.6%の位置に
    # あり(目視測定)、たまたま縦横比が近いため既存のfill_cell/fit_to_cellだけで
    # ほぼ一致している。一方AUPQ35/AUPQ78(下段)は同じ測り方でおよそ30.7%の位置に
    # あり、そのままだと緯度がずれる。上に余白を足してこの比率を36.6%に揃えてから
    # fit_to_cellする(縦横比・絵柄は変えず、位置だけ補正する)。
    AXFE578_40N_FRACTION = 0.366
    AUPQ_40N_FRACTION = 0.307

    def pad_top_to_match_latitude(img: Image.Image) -> Image.Image:
        h = img.height
        pad = (AXFE578_40N_FRACTION * h - AUPQ_40N_FRACTION * h) / (1 - AXFE578_40N_FRACTION)
        pad = max(0, int(round(pad)))
        if pad == 0:
            return img
        canvas = Image.new("RGB", (img.width, h + pad), "white")
        canvas.paste(img, (0, pad))
        return canvas

    # 緯度合わせの余白(pad_top_to_match_latitude)をそのままresize_to_heightすると、
    # セル上部に白い余白として残ってしまう。左下(絵柄の南側)を基準に固定したまま
    # 右上方向へ拡大し、その余白ぶんも絵柄で埋める(fill_cellのbottom/left版)。
    # 見た目の拡大率はENLARGE_FACTORで調整する(大きいほど北側が多く切れる代わりに
    # 絵柄が大きく見える)。
    ENLARGE_FACTOR = 1.0

    def enlarge_bottom_left(img_padded: Image.Image, native_w: int, native_h: int, target_h: int) -> Image.Image:
        # 余白を含まない場合の自然な幅(=そのままresize_to_heightした場合の幅)を基準に、
        # ENLARGE_FACTOR倍だけ余分に幅を要求することで、fill_cellが高さ方向にも
        # 余分に拡大し、南側(下端)を基準に北側(上端)を切り取る形になる。
        natural_w = max(1, int(round(native_w * target_h / native_h)))
        target_w = int(round(natural_w * ENLARGE_FACTOR))
        return fill_cell(img_padded, target_w, target_h, valign="bottom", halign="left")

    aupq35_upper_trim, aupq35_lower_trim, aupq35_lower_native = (None, None, None)
    if aupq35 is not None:
        u, l = split_top_bottom(aupq35)
        aupq35_upper_trim = trim_white_margins(u)
        aupq35_lower_native = trim_white_margins(l)
        aupq35_lower_trim = pad_top_to_match_latitude(aupq35_lower_native)
    aupq78_upper_trim, aupq78_lower_trim, aupq78_lower_native = (None, None, None)
    if aupq78 is not None:
        u, l = split_top_bottom(aupq78)
        aupq78_upper_trim = trim_white_margins(u)
        aupq78_lower_native = trim_white_margins(l)
        aupq78_lower_trim = pad_top_to_match_latitude(aupq78_lower_native)

    # 気象庁配信の並び(300hPa→500hPa→700hPa→850hPa、自然順)を優先する。この並びだと
    # AUPQ35の500hPaはcol3の1番目(FXFE502上段・500hPa VORT)ではなく2番目(地上図)の
    # 位置に来る(col3の4段はどれもほぼ同じ高さ(誤差5px程度)なので、位置自体はcol3と
    # 揃う)。
    aupq_row_sources = [aupq35_upper_trim, aupq35_lower_trim, aupq78_upper_trim, aupq78_lower_trim]
    aupq_row_natives = [None, aupq35_lower_native, None, aupq78_lower_native]
    aupq_bottom_cells = []
    for i, im in enumerate(aupq_row_sources):
        if im is None:
            continue
        target_h = col3_rows[i].height if i < len(col3_rows) else col12_h
        native = aupq_row_natives[i]
        if native is not None:
            cell = enlarge_bottom_left(im, native.width, native.height, target_h)
        else:
            cell = resize_to_height(im, target_h)
        aupq_bottom_cells.append(cell)

    # AUPA20はAUPQ35(300hPa・500hPa)と左右端を揃える。300hPaは自然な幅のまま
    # (resize_to_height)なので500hPa側より広いことがあり、その場合も足りなく
    # ならないよう、AUPQ35側2枚(aupq_bottom_cellsの先頭2つ)の最大幅に合わせる。
    # 幅を広げる分、縦横比を保ったまま拡大すると高さがheader_hを超えるため、
    # 下端(=AUPQ35との境目)を基準に上側を切り詰める(fill_cellのbottom版)。
    aupq35_widths = [c.width for c in aupq_bottom_cells[:2]]
    aupa20_target_w = max(aupq35_widths) if aupq35_widths else col12_w
    aupa20_cell = (
        fill_cell(aupa20, aupa20_target_w, col12_h, valign="bottom", halign="left")
        if aupa20 is not None
        else None
    )

    aupq_cells = ([aupa20_cell] if aupa20_cell is not None else []) + aupq_bottom_cells
    aupq_col = combine_vertical(aupq_cells, gap=LAYOUT_GAP, halign="left") if aupq_cells else None

    # ---- 左端(1列目): 一段目は空白(他列の一段目と同じ高さ)、AXJP140 / AXJP130 / 短期予報解説情報。
    # 3つとも切り取らず自然なサイズのまま並べる(上でAUPQ35/AUPQ78側をこの高さに合わせている)。
    left_col_w = col12_w
    # 短期予報解説資料(TKAISETU)を先に、AXJP140/AXJP130を後にする(上下逆)。
    left_parts = [Image.new("RGB", (left_col_w, header_h), "white")]
    if tkai_natural is not None:
        left_parts.append(tkai_natural)
    if axjp140_natural is not None:
        left_parts.append(axjp140_natural)
    if axjp130_natural is not None:
        left_parts.append(axjp130_natural)
    left_col = combine_vertical(left_parts, gap=LAYOUT_GAP, halign="left") if left_parts else None

    # 1段目(ヘッダー/AUPA20など)はどの列も特殊な構成で余白の性質がバラバラなので、
    # 列間の余白測定は2段目以降(header_h+LAYOUT_GAPより下)だけを見て行う。
    row2_top = header_h + LAYOUT_GAP

    grid_cols = [c for c in (aupq_col, col2, col3, col4, col5) if c is not None]
    grid_row = None
    col3_x_in_grid_row = 0
    if grid_cols:
        grid_h = max(c.height for c in grid_cols)
        padded_cols = [pad_to_height(c, grid_h) for c in grid_cols]
        # 各列が自身に内蔵している白余白の量(FXFE502等はまだ切り詰めていないため
        # 列ごとにバラバラ)に関わらず、絵柄同士の間隔が常にLAYOUT_GAPになるよう
        # 貼り付け位置をずらして結合する(画像そのものはトリミングしない)。
        measure_cols = [c.crop((0, min(row2_top, c.height - 1), c.width, c.height)) for c in padded_cols]
        grid_positions = visual_gap_positions(
            padded_cols, visual_gap=LAYOUT_GAP, measure_images=measure_cols
        )
        grid_w = max(x + c.width for x, c in zip(grid_positions, padded_cols))
        grid_row = Image.new("RGB", (grid_w, grid_h), "white")
        for x, c in zip(grid_positions, padded_cols):
            grid_row.paste(c, (x, 0))
        # col3(FXFE502列)はgrid_cols内でaupq_col,col2の次(index=2)にあたる。
        # FXJP854をこの列の真下に正確に揃えるため、実際の貼り付けx座標を控えておく。
        if col3 is not None:
            col3_index = grid_cols.index(col3)
            col3_x_in_grid_row = grid_positions[col3_index]
        # 1列目(left_col)はcol2(3列目)の元の高さに合わせて作られているが、
        # col2自体はここでgrid_h(4列目以降を含む最大高さ)まで白余白でパディングされる。
        # そのままだとleft_colの下端がgrid_rowの下端より短く、段差ができてしまうため、
        # left_colもgrid_hに合わせて下端をそろえる。
        if left_col is not None:
            left_col = pad_to_height(left_col, grid_h)

    top_level = [c.convert("RGB") for c in (left_col, grid_row) if c is not None]
    if not top_level:
        return None
    # 1列目とそれ以降の列も含め、列間の隙間(見た目)はすべてLAYOUT_GAPで統一する。
    # ここも1段目を除いた範囲(row2_top以降)だけで余白を測る。
    top_level_measure = [c.crop((0, min(row2_top, c.height - 1), c.width, c.height)) for c in top_level]
    top_level_positions = visual_gap_positions(
        top_level, visual_gap=LAYOUT_GAP, measure_images=top_level_measure
    )
    main_grid_w = max(x + c.width for x, c in zip(top_level_positions, top_level))
    main_grid_h = max(c.height for c in top_level)
    main_grid = Image.new("RGB", (main_grid_w, main_grid_h), "white")
    for x, c in zip(top_level_positions, top_level):
        main_grid.paste(c.convert("RGB"), (x, 0))
    # grid_row(2列目以降)がmain_grid内で実際に貼り付けられたx座標。
    grid_row_x_in_main = top_level_positions[-1] if left_col is not None and grid_row is not None else 0

    # FXJP854(T12/24/36/48)を、列4(FXFE502列)・列5(FXFE504列)の真下だけに
    # 独立した段として追加する(他列の下には余白のまま何も置かない)。
    fxjp854_parts = [im for im in (fxjp854_upper, fxjp854_lower) if im is not None]
    if fxjp854_parts:
        fxjp854_row = combine_horizontal(fxjp854_parts, gap=0, valign="top")
        left_pad_w = grid_row_x_in_main + col3_x_in_grid_row
        strip = Image.new("RGB", (main_grid.width, fxjp854_row.height), "white")
        strip.paste(fxjp854_row.convert("RGB"), (left_pad_w, 0))
        final_canvas = combine_vertical([main_grid, strip], gap=LAYOUT_GAP, halign="left")
    else:
        final_canvas = main_grid

    final_canvas = trim_bottom_whitespace(final_canvas, bottom_pad=20)
    final_canvas = trim_right_whitespace(final_canvas, right_pad=20)
    caption = jma_source_caption()
    final_canvas = append_caption_bar(final_canvas, caption)
    return pil_to_attachment(final_canvas, "DASHBOARD_JMA_DIRECT")


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
    # ① AXJP140.pdf 単体
    # -------------------------------------------------------------------------
    axjp_pages = fetch_pdf_pages(session, "AXJP140")
    if axjp_pages:
        append_output(images, pil_to_attachment(axjp_pages[0], "AXJP140"), 1)
    else:
        errors.append("AXJP140: download failed")

    # -------------------------------------------------------------------------
    # ② 数値 AUPA20 単体
    # -------------------------------------------------------------------------
    aupa_pages = fetch_pdf_pages(session, "AUPA20")
    if aupa_pages:
        append_output(images, pil_to_attachment(aupa_pages[0], "AUPA20"), 2)
    else:
        errors.append("AUPA20: download failed")

    # 週間4列結合は scripts/jma_layout4_weekly.py 側で(1日1回・JST正午)、
    # 全部入り（気象庁直接取得版）は scripts/jma_dashboard_direct.py 側で(1日4回)、
    # それぞれ別スケジュール・別ワークフローで生成する（このスクリプトでは作らない）。
    # 全部入りWCN版(build_layout_5)は07に置き換わったため、もう呼び出さない。

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
    notion_items: List[Tuple[str, str, str, str]],
    errors: List[str],
    extra_links: Optional[List[Tuple[str, str]]] = None,
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

    # 画像を先に貼り、関連リンクはその後に表示する。
    try:
        ordered_urls = [url for _, _label, _nfname, url in notion_items if url]
        if ordered_urls:
            if NOTION_IMPORT_IMAGES:
                items = [
                    (f"{nfname}.png", url, "image/png")
                    for _fname, _label, nfname, url in notion_items
                    if url
                ]
                append_imported_images_from_urls(
                    page_id,
                    items,
                    chunk=10,
                    timeout_seconds=NOTION_IMPORT_TIMEOUT_SECONDS,
                    poll_seconds=NOTION_IMPORT_POLL_SECONDS,
                )
            else:
                append_images(page_id, ordered_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] Notion image append/import failed: {e}")
        # 移行中の安全策: Notion取り込みに失敗したら従来の外部URL埋め込みへ戻す
        try:
            if all_urls:
                append_images(page_id, all_urls, chunk=30)
        except Exception as e2:
            print(f"[WARN] append_images fallback failed: {e2}")

    if extra_links:
        try:
            append_heading(page_id, "関連リンク", level=2)
            for cap, url in extra_links:
                append_bookmark(page_id, url, caption=cap)
        except Exception as e:
            print(f"[WARN] links failed: {e}")

    return page_id


IMAGE_EXTRA_LINKS: dict = {
    "04_LAYOUT_4_WEEKLY": [
        ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
    ],
    "06_LAYOUT_5_DASHBOARD": [
        ("気象庁 専門家向け資料", "https://www.jma.go.jp/jma/kishou/know/expert/index.html"),
        ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
        ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
    ],
    "07_DASHBOARD_JMA_DIRECT": [
        ("気象庁 専門家向け資料", "https://www.jma.go.jp/jma/kishou/know/expert/index.html"),
        ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
    ],
}


def discord_links_text() -> str:
    return "\n".join(["**参考リンク**"] + [f"🔗 [{t}](<{u}>)" for t, u in DISCORD_LINKS])


def notify_dm_subscribers(
    content: str,
    thumb_path: str,
    thumb_mime: str,
    *,
    push_title: str = "",
    push_url: str = "",
    pwa_category: str = "",
    pwa_issue_time: str = "",
) -> None:
    """有料購読者（Notion管理）へ、公開チャンネルと同じ内容を配信する。
    Discord経由の購読者にはDM、PWA/メールログイン経由の購読者には
    OneSignal Web Pushを送る（どちらも同じNotion DBのStatus判定を共有）。
    購読者取得や送信に失敗しても、公開チャンネルへの投稿自体は
    既に完了しているため、ここでの例外は握りつぶしてログのみ出す。"""
    try:
        discord_ids = get_active_discord_ids()
    except Exception as e:
        print(f"[WARN] DM購読者リスト取得失敗: {e}")
        discord_ids = []

    if discord_ids:
        with open(thumb_path, "rb") as f:
            thumb_bytes = f.read()
        filename = "thumb.jpg" if thumb_mime == "image/jpeg" else "thumb.png"
        send_dm_to_all(discord_ids, content, thumb_bytes, filename)

    try:
        emails = get_active_emails()
    except Exception as e:
        print(f"[WARN] Push購読者リスト取得失敗: {e}")
        emails = []

    if emails and push_title:
        try:
            send_push_to_all(emails, push_title, "新しい配信が届きました", url=push_url or None)
        except Exception as e:
            print(f"[WARN] OneSignal push送信失敗: {e}")

    if pwa_category and push_title and push_url:
        record_recent_item(push_title, push_url, pwa_category, pwa_issue_time)


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
        if filename in DISCORD_SKIP_FILENAMES:
            continue
        title = DISCORD_TITLES.get(filename, filename)
        extra_links = IMAGE_EXTRA_LINKS.get(filename, [])
        if extra_links:
            title += "\n" + "\n".join(f"🔗 [{t}](<{u}>)" for t, u in extra_links)
        src_path = os.path.join(OUTPUT_DIR, f"{filename}.png")

        # 4枚目・5枚目の結合画像は、Discordには軽量サムネイルを1枚だけ添付する。
        # 本文にR2の高解像度PNG URLを入れ、URLプレビューは抑制する。
        # これで「サムネイル1枚 + その下にURL表記」になる。
        if filename in DISCORD_R2_PNG_LINK_FILENAMES:
            if idx < len(all_urls) and all_urls[idx]:
                highres_url = all_urls[idx]
                content = (
                    f"{init_jst} / {title}\n"
                    f"📥 [高解像度PNGをダウンロード（30日間有効）](<{highres_url}>)"
                )

                if os.path.exists(src_path):
                    try:
                        thumb_path, thumb_mime = make_discord_thumbnail(src_path)
                        print(f"[INFO] Discord thumbnail: {thumb_path} size={os.path.getsize(thumb_path)} bytes")
                        post_discord_file_image(
                            webhook_url=webhook_url,
                            title=content,
                            image_path=thumb_path,
                            mime=thumb_mime,
                            suppress_embeds=True,
                        )
                        if filename in DM_SAFE_FILENAMES:
                            notify_dm_subscribers(
                                content,
                                thumb_path,
                                thumb_mime,
                                push_title=DISCORD_TITLES.get(filename, filename),
                                push_url=highres_url,
                                pwa_category=PWA_CATEGORY_BY_FILENAME.get(filename, ""),
                                pwa_issue_time=init_jst,
                            )
                    except Exception as e:
                        print(f"[WARN] Discord thumbnail upload failed: {src_path} / {e}")
                        # 添付に失敗した場合だけ、R2 URLの自動プレビューに戻す。
                        post_discord_text(content)
                else:
                    print(f"[WARN] Discord thumbnail source missing: {src_path}")
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
        print("=== Start Weathercaster JMA Weather Map (Custom Layout PNG / 2 outputs) ===")

        issue_dt_jst = issue_base_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        # 先頭prefixは normalize_key() が付けるので、ここは日付/RJTD だけにする。
        run_prefix = f"{day}/RJTD_{rjtd}"

        images, errors = build_outputs()
        all_urls, rep_url = upload_to_r2(run_prefix, images)

        url_map = dict(zip(OUTPUT_FILENAMES, all_urls))
        notion_items = [(fname, label, nfname, url_map.get(fname, "")) for fname, label, nfname in NOTION_ORDER]

        page_id = notion_write_db(
            issue_dt_jst=issue_dt_jst,
            rjtd=rjtd,
            run_prefix=run_prefix,
            rep_url=rep_url,
            all_urls=all_urls,
            notion_items=notion_items,
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
            if errors:
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


def build_dashboard_jma_only() -> Tuple[List[Attachment], List[str]]:
    """
    全部入り（気象庁直接取得版）だけを作る。WCN（Weathercaster.jp）には
    一切アクセスしないため、weathercaster_session()は不要。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []

    dashboard_jma_att = build_layout_dashboard_jma(errors)
    if dashboard_jma_att:
        fixed = rename_attachment(dashboard_jma_att, "07_DASHBOARD_JMA_DIRECT")
        images.append(fixed)
        print(f"[OUT] {fixed[0]}")

    for fname, data, _ in images:
        try:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(data)
        except Exception:
            pass

    print(f"[OK] output image count: {len(images)}")
    return images, errors


def main_dashboard_jma() -> None:
    """
    全部入り（気象庁直接取得版）専用のエントリポイント。
    WCNを経由しないため気象庁の公開サイクル(UTC 00/12時、1日2回)に合わせて
    別スケジュールで実行する(scripts/jma_dashboard_direct.py)。
    """
    try:
        print("=== Start JMA-direct Dashboard (全部入り・気象庁版) ===")

        issue_dt_jst = issue_base_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        # issue_dt_jstは09:00/21:00の固定枠に丸められるため、同じ枠内で1日に
        # 複数回実行されると(例: 11:30と17:00はどちらも09:00枠)同じR2キーに
        # なってしまう。実際の実行時刻(分秒)を付けてキーを一意にする。
        run_prefix = f"{day}/RJTD_{rjtd}_{now_jst().strftime('%H%M%S')}"

        images, errors = build_dashboard_jma_only()
        all_urls, rep_url = upload_to_r2(run_prefix, images)

        filename = "07_DASHBOARD_JMA_DIRECT"
        url = all_urls[0] if all_urls else ""

        notion_items = [(filename, "高層天気図・数値予報天気図 結合図", "DASHBOARD_JMA_DIRECT", url)]
        page_id = notion_write_db(
            issue_dt_jst=issue_dt_jst,
            rjtd=rjtd,
            run_prefix=run_prefix,
            rep_url=rep_url,
            all_urls=all_urls,
            notion_items=notion_items,
            errors=errors,
            extra_links=IMAGE_EXTRA_LINKS.get(filename, []),
        )

        notion_url = notion_page_url(page_id) if page_id else ""
        if notion_url:
            print(f"[OK] Notion URL: {notion_url}")

        try:
            if discord_jma_enabled() and url:
                init_jst = issue_dt_jst.strftime("%Y-%m-%d %H:%M JST")
                title = DISCORD_TITLES.get(filename, filename)
                extra_links = IMAGE_EXTRA_LINKS.get(filename, [])
                if extra_links:
                    title += "\n" + "\n".join(f"🔗 [{t}](<{u}>)" for t, u in extra_links)
                content = (
                    f"{init_jst} / {title}\n"
                    f"📥 [高解像度PNGをダウンロード（30日間有効）](<{url}>)"
                )

                src_path = os.path.join(OUTPUT_DIR, f"{filename}.png")
                if os.path.exists(src_path):
                    thumb_path, thumb_mime = make_discord_thumbnail(
                        src_path,
                        caption_text=jma_source_caption(),
                    )
                    post_discord_file_image(
                        webhook_url=discord_jma_webhook_url(),
                        title=content,
                        image_path=thumb_path,
                        mime=thumb_mime,
                        suppress_embeds=True,
                    )
                    # 有料DM配信対象は気象庁直接取得版のみ(DM_SAFE_FILENAMES参照)。
                    notify_dm_subscribers(
                        content,
                        thumb_path,
                        thumb_mime,
                        push_title=DISCORD_TITLES.get(filename, filename),
                        push_url=url,
                        pwa_category=PWA_CATEGORY_BY_FILENAME.get(filename, ""),
                        pwa_issue_time=init_jst,
                    )
                else:
                    print(f"[WARN] Discord thumbnail source missing: {src_path}")

            if errors:
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


def build_layout4_only() -> Tuple[List[Attachment], List[str]]:
    """
    週間4列結合だけを作る。SKAISETU/FEFE19/FXXN519/FZCX50はすべて気象庁が
    自ら公開しているデータのみで構成するため、WCN（Weathercaster.jp）には
    一切アクセスしない。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []

    layout4_att = build_layout4_jma_direct(errors)
    if layout4_att:
        fixed = rename_attachment(layout4_att, "04_LAYOUT_4_WEEKLY")
        images.append(fixed)
        print(f"[OUT] {fixed[0]}")

    for fname, data, _ in images:
        try:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(data)
        except Exception:
            pass

    print(f"[OK] output image count: {len(images)}")
    return images, errors


def main_layout4() -> None:
    """
    週間4列結合専用のエントリポイント。
    元になるSKAISETU（週間予報解説資料）はJST 10時頃更新・1日1回のため、
    正午JST頃の1日1回だけ実行する(scripts/jma_layout4_weekly.py)。
    気象庁公開データのみで構成しているため、有料DM配信の対象にもなる
    （DM_SAFE_FILENAMES参照）。
    """
    try:
        print("=== Start Weekly 4-column Layout (週間4列結合) ===")

        issue_dt_jst = issue_base_jst()
        rjtd = issue_dt_jst.strftime("%d%H%M")
        day = issue_dt_jst.strftime("%Y%m%d")
        # issue_dt_jstは固定枠に丸められるため、手動再実行等で同じ枠内に
        # 複数回実行されると同じR2キーになってしまう。実際の実行時刻(分秒)を
        # 付けてキーを一意にする。
        run_prefix = f"{day}/RJTD_{rjtd}_{now_jst().strftime('%H%M%S')}"

        images, errors = build_layout4_only()
        all_urls, rep_url = upload_to_r2(run_prefix, images)

        filename = "04_LAYOUT_4_WEEKLY"
        url = all_urls[0] if all_urls else ""
        # Notion配信は全部入り・アメダス・ADV・ガイダンスの4種類のみのため、
        # 週間4列結合はNotionに書き込まない(公開Discord + 有料DMのみ)。

        try:
            if discord_jma_enabled() and url:
                init_jst = issue_dt_jst.strftime("%Y-%m-%d %H:%M JST")
                title = DISCORD_TITLES.get(filename, filename)
                extra_links = IMAGE_EXTRA_LINKS.get(filename, [])
                if extra_links:
                    title += "\n" + "\n".join(f"🔗 [{t}](<{u}>)" for t, u in extra_links)
                content = (
                    f"{init_jst} / {title}\n"
                    f"📥 [高解像度PNGをダウンロード（30日間有効）](<{url}>)"
                )

                src_path = os.path.join(OUTPUT_DIR, f"{filename}.png")
                if os.path.exists(src_path):
                    thumb_path, thumb_mime = make_discord_thumbnail(
                        src_path,
                        caption_text=jma_source_caption(),
                    )
                    post_discord_file_image(
                        webhook_url=discord_jma_webhook_url(),
                        title=content,
                        image_path=thumb_path,
                        mime=thumb_mime,
                        suppress_embeds=True,
                    )
                    if filename in DM_SAFE_FILENAMES:
                        notify_dm_subscribers(
                            content,
                            thumb_path,
                            thumb_mime,
                            push_title=DISCORD_TITLES.get(filename, filename),
                            push_url=url,
                            pwa_category=PWA_CATEGORY_BY_FILENAME.get(filename, ""),
                            pwa_issue_time=init_jst,
                        )
                else:
                    print(f"[WARN] Discord thumbnail source missing: {src_path}")

            if errors:
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
