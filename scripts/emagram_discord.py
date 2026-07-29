#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# scripts/emagram_discord.py
#
# 気象庁指定の高層観測15地点のエマグラム（Stuve線図）を
# ワイオミング大学 (weather.arcc.uwyo.edu) の高層観測アーカイブから取得し、
# 1枚に結合してDiscordへ配信する。
#
# 観測は 00Z(09時JST) / 12Z(21時JST) の1日2回。
# データ反映まで余裕を見て、観測から4時間後（13時/翌01時JST）に実行する想定。
#
# 画像は静的URL（/upperair/imgs/{YYYYMMDDHH}.{地点番号}.stuve.png）に
# 直接は存在せず、/wsgi/sounding?...type=PNG:STUVE... への初回アクセス時に
# サーバー側で遅延生成される。そのため必ず一度 /wsgi/sounding を叩いてから
# 静的URLを参照する。
#
# 地点によっては実行時点でまだサーバー側の画像生成が間に合っていないことが
# ある。地点間で観測時刻がずれると混乱するため前回観測への遡りはせず、
# その場合は「データなし」のプレースホルダー画像を出す。
#
# 結合した高解像度PNGはR2へアップロードし、Discordにはサムネイル1枚と
# 「★高解像度PNGを表示」というテキストリンクだけを投稿する
# （weather_map.py の LAYOUT_4_WEEKLY / DASHBOARD と同じ形式）。

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module.utils.r2_utils import put_bytes, make_url
from module.utils.notion_subscribers import get_active_discord_ids
from module.utils.discord_dm import send_dm_to_all

STATIONS = [
    ("47401", "稚内"),
    ("47412", "札幌"),
    ("47418", "釧路"),
    ("47582", "秋田"),
    ("47600", "輪島"),
    ("47646", "館野"),
    ("47678", "八丈島"),
    ("47741", "松江"),
    ("47778", "潮岬"),
    ("47807", "福岡"),
    ("47827", "鹿児島"),
    ("47909", "名瀬"),
    ("47918", "石垣島"),
    ("47945", "南大東島"),
    ("47971", "父島"),
]

BASE = "https://weather.arcc.uwyo.edu"
SOUNDING_URL = BASE + "/wsgi/sounding"
IMG_SRC_RE = re.compile(r'<img src="(/upperair/imgs/[^"]+\.png)">')

GRID_COLS = 5
GRID_ROWS = 3
CELL_W = 800
CELL_H = 640
LABEL_H = 60

THUMB_MAX_WIDTH = int(os.environ.get("DISCORD_THUMB_MAX_WIDTH", "1400"))
THUMB_JPEG_QUALITY = int(os.environ.get("DISCORD_THUMB_JPEG_QUALITY", "85"))
R2_RETENTION_DAYS = os.environ.get("R2_RETENTION_DAYS", "30")

REQUEST_TIMEOUT_SECONDS = 60
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


def target_sounding_time() -> datetime:
    """直近の観測時刻（00Z or 12Z）を返す。"""
    now = datetime.now(timezone.utc)
    hour = 0 if now.hour < 12 else 12
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def fetch_image(stnm: str, dt: datetime) -> bytes | None:
    """指定地点・時刻のStuve画像を生成させ、PNGバイト列を返す（データが無ければNone）。"""
    params = {
        "datetime": dt.strftime("%Y-%m-%d %H:00:00"),
        "id": stnm,
        "type": "PNG:STUVE",
        "src": "FM35",
    }
    try:
        r = requests.get(SOUNDING_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: {stnm} 取得中に例外が発生しました: {exc}", file=sys.stderr)
        return None

    if r.status_code != 200:
        print(f"SKIP: {stnm} status={r.status_code}")
        return None

    m = IMG_SRC_RE.search(r.text)
    if not m:
        print(f"SKIP (データなし): {stnm}")
        return None

    img_url = BASE + m.group(1)
    try:
        img_r = requests.get(img_url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: {stnm} 画像ダウンロード中に例外が発生しました: {exc}", file=sys.stderr)
        return None

    if img_r.status_code != 200:
        print(f"SKIP: {stnm} 画像ダウンロード status={img_r.status_code}")
        return None

    return img_r.content


def load_font(candidates: list, size: int):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def placeholder_image(name: str, dt: datetime) -> bytes:
    """データが取得できなかった地点用の「データなし」プレースホルダー画像。"""
    img = Image.new("RGB", (CELL_W, CELL_H), "white")
    draw = ImageDraw.Draw(img)

    font_large = load_font(CJK_BOLD_CANDIDATES, 40)
    font_small = load_font(CJK_REGULAR_CANDIDATES, 24)

    lines = [
        ("データなし", font_large),
        (f"{dt.strftime('%Y-%m-%d %H')}Z", font_small),
    ]
    total_h = sum(draw.textbbox((0, 0), t, font=f)[3] for t, f in lines) + 20 * (len(lines) - 1)
    y = (CELL_H - total_h) // 2
    for text, font in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((CELL_W - w) // 2, y), text, fill="black", font=font)
        y += (bbox[3] - bbox[1]) + 20

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


RETRY_COUNT = 3
RETRY_WAIT_SECONDS = 180


def fetch_image_with_fallback(stnm: str, name: str, dt: datetime) -> bytes:
    """当該時刻の画像を確保する。無ければプレースホルダー。
    地点間で時系列がずれるのを避けるため、前回観測への遡りはしない。
    一部地点はサーバー側の反映が観測から数時間後にずれ込むことがあるため、
    取得できない場合は少し待って数回リトライしてから諦める。"""
    img_bytes = fetch_image(stnm, dt)
    if img_bytes:
        return img_bytes

    for attempt in range(1, RETRY_COUNT + 1):
        print(f"RETRY {attempt}/{RETRY_COUNT}: {name} を{RETRY_WAIT_SECONDS}秒後に再試行します")
        time.sleep(RETRY_WAIT_SECONDS)
        img_bytes = fetch_image(stnm, dt)
        if img_bytes:
            print(f"RETRY OK: {name}")
            return img_bytes

    print(f"NO DATA: {name} はプレースホルダーを使用")
    return placeholder_image(name, dt)


def build_grid_image(stations_with_images: list) -> bytes:
    """15地点分を1枚のグリッド画像に結合する（地点名ラベル付き）。"""
    canvas_w = GRID_COLS * CELL_W
    canvas_h = GRID_ROWS * (CELL_H + LABEL_H)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    font = load_font(CJK_BOLD_CANDIDATES, 32)

    for idx, (name, img_bytes) in enumerate(stations_with_images):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = col * CELL_W
        y = row * (CELL_H + LABEL_H)

        bbox = draw.textbbox((0, 0), name, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x + (CELL_W - tw) // 2, y + (LABEL_H - th) // 2), name, fill="black", font=font)

        with Image.open(BytesIO(img_bytes)) as im:
            rgb = im.convert("RGB")
            if rgb.size != (CELL_W, CELL_H):
                rgb = rgb.resize((CELL_W, CELL_H), Image.Resampling.LANCZOS)
            canvas.paste(rgb, (x, y + LABEL_H))

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def append_caption_bar(img_bytes: bytes, dt: datetime, *, font_size: int = 26, pad: int = 14) -> bytes:
    """画像の下に、作成日時(UTC)・出典を記した余白バーを追加する。"""
    font = load_font(CJK_REGULAR_CANDIDATES, font_size)
    text = (
        f"作成日時: {dt.strftime('%Y年%m月%d日 %H:%M')} UTC"
        "　出典: University of Wyoming 高層観測アーカイブ (weather.arcc.uwyo.edu)"
        "　作成: Synoptic Chart Premium"
    )

    with Image.open(BytesIO(img_bytes)) as im:
        rgb = im.convert("RGB")

    tmp = Image.new("RGB", (10, 10), "white")
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    bar_h = text_h + pad * 2

    canvas = Image.new("RGB", (rgb.width, rgb.height + bar_h), "white")
    canvas.paste(rgb, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, rgb.height + pad - bbox[1]), text, fill=(90, 90, 90), font=font)

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumbnail(img_bytes: bytes) -> bytes:
    with Image.open(BytesIO(img_bytes)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        if w > THUMB_MAX_WIDTH:
            new_h = max(1, int(h * (THUMB_MAX_WIDTH / w)))
            rgb = rgb.resize((THUMB_MAX_WIDTH, new_h), Image.Resampling.LANCZOS)
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


def build_content(dt: datetime, highres_url: str) -> str:
    return (
        f"🌡️ **エマグラム / {dt.strftime('%Y-%m-%d %H')}Z**\n"
        f"**[★高解像度PNG（R2 / {R2_RETENTION_DAYS}日保存）を表示](<{highres_url}>)**"
    )


def notify_dm_subscribers(content: str, thumb_bytes: bytes) -> None:
    """有料DM購読者（Notion管理）へ、公開チャンネルと同じ内容をDMする。"""
    try:
        discord_ids = get_active_discord_ids()
    except Exception as e:
        print(f"[WARN] DM購読者リスト取得失敗: {e}")
        return

    if not discord_ids:
        return

    send_dm_to_all(discord_ids, content, thumb_bytes, "emagram_thumb.jpg")


def post_combined(webhook_url: str, dt: datetime, thumb_bytes: bytes, highres_url: str) -> bool:
    content = build_content(dt, highres_url)
    payload = {
        "username": "エマグラム",
        "content": content,
        "flags": 4,  # SUPPRESS_EMBEDS: URLの自動プレビューを抑制
    }
    files = {
        "payload_json": (None, json.dumps(payload)),
        "files[0]": ("emagram_thumb.jpg", thumb_bytes, "image/jpeg"),
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
    webhook_url = os.environ.get("DISCORD_EMAGRAM_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_EMAGRAM_WEBHOOK_URL未設定", file=sys.stderr)
        return 1

    dt = target_sounding_time()

    stations_with_images = [
        (name, fetch_image_with_fallback(stnm, name, dt)) for stnm, name in STATIONS
    ]

    combined = build_grid_image(stations_with_images)
    combined = append_caption_bar(combined, dt)

    r2_key = f"{dt.strftime('%Y%m%d%H')}.png"
    put_bytes(r2_key, combined, content_type="image/png")
    highres_url = make_url(r2_key)
    print(f"R2 UPLOADED: {highres_url}")

    thumb = make_thumbnail(combined)

    if post_combined(webhook_url, dt, thumb, highres_url):
        print("POSTED")
        notify_dm_subscribers(build_content(dt, highres_url), thumb)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
