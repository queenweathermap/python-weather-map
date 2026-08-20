# -*- coding: utf-8 -*-
#
# module/jobs/windprofiler.py
#
# 気象庁「ウィンドプロファイラ」(WINDAS) 全33地点のチャートを
# 公式ページ (https://www.jma.go.jp/bosai/windprofiler/) から
# Playwrightでスクリーンショットし、1枚の画像（4列×9行、地点ごとの解像度は
# 変えない）に結合してDiscordへ配信する。
#
# チャートはJS(SVG)描画のSPAで、ページ内の #wpr-chart 要素が
# 「地点名・緯度経度」ラベルとグラフ本体（時間の向き矢印込み）をまとめて含む。
# 右側の凡例(.wpr-sub)は全地点共通なのでスクリーンショットには含めない。
# 地点切替はフルリロードせず location.hash を書き換えるだけで良い
# (#code=XXXXX&type=chart)。
#
# データは観測から10〜20分程度で反映される(ラジオゾンデより大幅に速い)ため、
# 実行時刻を基準にその場の最新表示をそのまま撮影すればよい。
# 表示される時間軸はサイト側で約7時間分のローリングウィンドウになっているため、
# 6時間おきに実行すれば約1時間分の重なりを持って1日をカバーできる。

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import ceil
from pathlib import Path
from typing import List, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from module.utils.r2_utils import put_bytes, make_url

JST = timezone(timedelta(hours=9))

PORTAL_URL = "https://www.jma.go.jp/bosai/windprofiler/"

# 気象庁公式の地点コード表 (const/station.json) の並び順のまま。
# https://www.jma.go.jp/bosai/windprofiler/#code=XXXXX&type=chart
STATIONS_ALL: List[Tuple[str, str]] = [
    ("47406", "留萌"),
    ("47417", "帯広"),
    ("47423", "室蘭"),
    ("47570", "若松"),
    ("47585", "宮古"),
    ("47587", "酒田"),
    ("47590", "仙台"),
    ("47612", "高田"),
    ("47616", "福井"),
    ("47626", "熊谷"),
    ("47629", "水戸"),
    ("47636", "名古屋"),
    ("47640", "河口湖"),
    ("47656", "静岡"),
    ("47663", "尾鷲"),
    ("47674", "勝浦"),
    ("47678", "八丈島"),
    ("47746", "鳥取"),
    ("47755", "浜田"),
    ("47795", "美浜"),
    ("47800", "厳原"),
    ("47805", "平戸"),
    ("47815", "大分"),
    ("47819", "熊本"),
    ("47822", "延岡"),
    ("47836", "屋久島"),
    ("47848", "市来"),
    ("47891", "高松"),
    ("47893", "高知"),
    ("47898", "清水"),
    ("47909", "名瀬"),
    ("47912", "与那国島"),
    ("47945", "南大東島"),
]

BASE_URL = "https://www.jma.go.jp/bosai/windprofiler/"
CHART_SELECTOR = "#wpr-chart"
STATION_LABEL_SELECTOR = "#wpr-station"

VP_W = int(os.environ.get("WINDPROFILER_VIEWPORT_WIDTH", "1050"))
VP_H = int(os.environ.get("WINDPROFILER_VIEWPORT_HEIGHT", "760"))
INITIAL_WAIT_MS = int(os.environ.get("WINDPROFILER_INITIAL_WAIT_MS", "2500"))
SWITCH_WAIT_MS = int(os.environ.get("WINDPROFILER_WAIT_MS", "1200"))
SWITCH_TIMEOUT_MS = int(os.environ.get("WINDPROFILER_SWITCH_TIMEOUT_MS", "5000"))

GRID_COLS = 4
CELL_W = 752
CELL_H = 545

THUMB_MAX_WIDTH = int(os.environ.get("DISCORD_THUMB_MAX_WIDTH", "1400"))
THUMB_JPEG_QUALITY = int(os.environ.get("DISCORD_THUMB_JPEG_QUALITY", "85"))
R2_RETENTION_DAYS = os.environ.get("R2_RETENTION_DAYS", "30")

DISCORD_TIMEOUT_SECONDS = 30

CJK_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",  # macOS
]
CJK_REGULAR_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",  # macOS
]


def _jst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def load_font(candidates: list, size: int):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def placeholder_image(name: str) -> bytes:
    """撮影に失敗した地点用の「データなし」プレースホルダー画像。"""
    img = Image.new("RGB", (CELL_W, CELL_H), "white")
    draw = ImageDraw.Draw(img)

    font_large = load_font(CJK_BOLD_CANDIDATES, 36)
    font_small = load_font(CJK_REGULAR_CANDIDATES, 22)

    lines = [(name, font_small), ("データなし", font_large)]
    total_h = sum(draw.textbbox((0, 0), t, font=f)[3] for t, f in lines) + 16
    y = (CELL_H - total_h) // 2
    for text, font in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((CELL_W - w) // 2, y), text, fill="black", font=font)
        y += (bbox[3] - bbox[1]) + 16

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def screenshot_all_stations() -> List[Tuple[str, bytes]]:
    """全33地点の #wpr-chart を撮影して [(地点名, PNGバイト列), ...] を返す。
    個別地点の撮影に失敗した場合はプレースホルダーで埋める。"""
    from playwright.sync_api import sync_playwright

    results: List[Tuple[str, bytes]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport={"width": VP_W, "height": VP_H})
            page = ctx.new_page()

            first_code, first_name = STATIONS_ALL[0]
            page.goto(f"{BASE_URL}#code={first_code}&type=chart", wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(INITIAL_WAIT_MS)

            for i, (code, name) in enumerate(STATIONS_ALL):
                try:
                    if i > 0:
                        page.evaluate(f"location.hash = 'code={code}&type=chart'")
                        try:
                            page.wait_for_function(
                                f"document.querySelector('{STATION_LABEL_SELECTOR}') "
                                f"&& document.querySelector('{STATION_LABEL_SELECTOR}').textContent.includes('{name}')",
                                timeout=SWITCH_TIMEOUT_MS,
                            )
                        except Exception:
                            print(f"[WARN] {name}: ラベル切替待ちがタイムアウトしました。そのまま撮影します")
                        page.wait_for_timeout(SWITCH_WAIT_MS)

                    raw = page.locator(CHART_SELECTOR).screenshot()
                    print(f"[OK] {name} ({code})  {len(raw):,} bytes")
                    results.append((name, raw))
                except Exception as e:
                    print(f"[WARN] {name} ({code}) 撮影失敗: {e}")
                    results.append((name, placeholder_image(name)))
        finally:
            browser.close()

    return results


def build_grid_image(stations_with_images: List[Tuple[str, bytes]], *, cols: int = GRID_COLS) -> bytes:
    """地点分のチャート画像(地点名ラベル込み)を1枚のグリッドに結合する。"""
    rows = ceil(len(stations_with_images) / cols)
    canvas_w = cols * CELL_W
    canvas_h = rows * CELL_H
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")

    for idx, (_name, img_bytes) in enumerate(stations_with_images):
        col = idx % cols
        row = idx // cols
        x = col * CELL_W
        y = row * CELL_H

        with Image.open(BytesIO(img_bytes)) as im:
            rgb = im.convert("RGB")
            if rgb.size != (CELL_W, CELL_H):
                rgb = rgb.resize((CELL_W, CELL_H), Image.Resampling.LANCZOS)
            canvas.paste(rgb, (x, y))

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def caption_text_for(dt_jst: datetime) -> str:
    return (
        f"作成日時: {dt_jst.strftime('%Y年%m月%d日 %H:%M')} JST"
        "　出典: 気象庁 ウィンドプロファイラ (jma.go.jp/bosai/windprofiler)"
        "　作成: 177chart"
    )


def _wrap_caption_lines(text: str, font, available_w: int, tmp_draw) -> list:
    segments = text.split("　")
    lines = []
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
    img_bytes: bytes,
    dt_jst: datetime,
    *,
    font_size: int = 26,
    pad: int = 14,
    align: str = "right",
    min_font_size: int = 14,
) -> bytes:
    text = caption_text_for(dt_jst)

    with Image.open(BytesIO(img_bytes)) as im:
        rgb = im.convert("RGB")

    tmp = Image.new("RGB", (10, 10), "white")
    draw_tmp = ImageDraw.Draw(tmp)
    available_w = max(1, rgb.width - pad * 2)

    size = font_size
    while True:
        font = load_font(CJK_REGULAR_CANDIDATES, size)
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

    canvas = Image.new("RGB", (rgb.width, rgb.height + bar_h), "white")
    canvas.paste(rgb, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = rgb.height + pad
    for ln, bbox in zip(lines, line_bboxes):
        w = bbox[2] - bbox[0]
        x = (rgb.width - pad - w) if align == "right" else pad
        draw.text((x, y - bbox[1]), ln, fill=(90, 90, 90), font=font)
        y += line_h + line_gap

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumbnail(img_bytes: bytes, dt_jst: datetime, *, baked_font_size: int = 26, thumb_font_size: int = 20) -> bytes:
    baked_font = load_font(CJK_REGULAR_CANDIDATES, baked_font_size)
    tmp = Image.new("RGB", (10, 10), "white")
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), caption_text_for(dt_jst), font=baked_font)
    baked_bar_h = (bbox[3] - bbox[1]) + 14 * 2

    with Image.open(BytesIO(img_bytes)) as im:
        rgb = im.convert("RGB")
        if 0 < baked_bar_h < rgb.height:
            rgb = rgb.crop((0, 0, rgb.width, rgb.height - baked_bar_h))

        w, h = rgb.size
        if w > THUMB_MAX_WIDTH:
            new_h = max(1, int(h * (THUMB_MAX_WIDTH / w)))
            rgb = rgb.resize((THUMB_MAX_WIDTH, new_h), Image.Resampling.LANCZOS)

        buf = BytesIO()
        rgb.save(buf, format="PNG")
        rgb_bytes = append_caption_bar(buf.getvalue(), dt_jst, font_size=thumb_font_size, pad=10)

    with Image.open(BytesIO(rgb_bytes)) as im2:
        out = BytesIO()
        im2.convert("RGB").save(out, format="JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
        return out.getvalue()


def build_content(dt_jst: datetime, url: str) -> str:
    return "\n".join([
        f"🌀 **ウィンドプロファイラ（高層風） / {dt_jst.strftime('%Y-%m-%d %H:%M')} JST**",
        f"🔗 [気象庁 ウィンドプロファイラ（地点別）](<{PORTAL_URL}>)",
        f"📥 [高解像度PNGをダウンロード（{R2_RETENTION_DAYS}日間有効）](<{url}>)",
    ])


def post_combined(webhook_url: str, dt_jst: datetime, thumb: bytes, url: str) -> bool:
    content = build_content(dt_jst, url)
    payload = {
        "username": "ウィンドプロファイラ",
        "content": content,
        "flags": 4,  # SUPPRESS_EMBEDS
    }
    files = {
        "payload_json": (None, json.dumps(payload)),
        "files[0]": ("windprofiler.jpg", thumb, "image/jpeg"),
    }

    try:
        r = requests.post(webhook_url, files=files, timeout=DISCORD_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: Discord投稿中に例外が発生しました: {exc}", file=sys.stderr)
        return False

    if 200 <= r.status_code < 300:
        return True

    print(f"ERROR: Discord投稿失敗 status={r.status_code} body={r.text[:500]}", file=sys.stderr)
    return False


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WINDPROFILER_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_WINDPROFILER_WEBHOOK_URL未設定", file=sys.stderr)
        return 1

    dt_jst = _jst_now()

    all_images = screenshot_all_stations()

    now_utc = datetime.now(timezone.utc)
    key_stub = f"{dt_jst.strftime('%Y%m%d%H%M')}_{now_utc.strftime('%S')}"

    combined = build_grid_image(all_images)
    combined = append_caption_bar(combined, dt_jst)

    r2_key = f"{key_stub}.png"
    put_bytes(r2_key, combined, content_type="image/png")
    url = make_url(r2_key)
    print(f"R2 UPLOADED: {url}")

    thumb = make_thumbnail(combined, dt_jst)

    if post_combined(webhook_url, dt_jst, thumb, url):
        print("POSTED")
        return 0

    return 1
