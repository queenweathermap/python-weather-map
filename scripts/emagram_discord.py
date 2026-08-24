#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# scripts/emagram_discord.py
#
# 気象庁指定の高層観測15地点のエマグラム（Stuve線図）を
# ワイオミング大学 (weather.arcc.uwyo.edu) の高層観測アーカイブから取得し、
# 1枚に結合してDiscordへ配信する。
#
# 観測は 00Z(09時JST) / 12Z(21時JST) の1日2回だが、配信は12Z回
# （観測から7時間後、UTC 19:00 = 翌04:00JST）に一本化した「前日まとめ」。
# この時点では同日00Z(19時間経過)・12Z(7時間経過)ともに十分収録済みのため、
# 1回の実行で両方を1地点=1組(00Z/12Z横並び)としてまとめて配信する。
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
# 「📥高解像度PNGを表示」というテキストリンクだけを投稿する
# （weather_map.py の LAYOUT_4_WEEKLY / DASHBOARD と同じ形式）。

from __future__ import annotations

import functools
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

from module.utils.r2_utils import put_bytes, get_bytes, make_url
from module.utils.notion_subscribers import get_active_discord_ids, get_active_emails
from module.utils.discord_dm import send_dm_to_all
from module.utils.onesignal_push import send_push_to_all
from module.utils.recent_items import record_recent_item

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

CELL_W = 800
CELL_H = 640
LABEL_H = 60

THUMB_MAX_WIDTH = int(os.environ.get("DISCORD_THUMB_MAX_WIDTH", "1400"))
THUMB_JPEG_QUALITY = int(os.environ.get("DISCORD_THUMB_JPEG_QUALITY", "85"))
R2_RETENTION_DAYS = os.environ.get("R2_RETENTION_DAYS", "30")

# 有料購読はPWA配信(OneSignal Push)のみに一本化したため、Discord DMは既定で停止する。
# 既存のDiscord購読者向けに再開したくなった場合は、workflowのenvに
# DISCORD_DM_ENABLE: "1" を追加するだけで良い(コードの削除はまだしていない)。
DISCORD_DM_ENABLE = os.environ.get("DISCORD_DM_ENABLE", "0").strip().lower() in ("1", "true", "yes", "on")

# OneSignal pushの遷移先。以前は配信画像のR2直URLを指していたが、iOSの
# ホーム画面追加(スタンドアロン)アプリでは外部ドメインへの直リンクが
# ツールバーの無い画面のまま身動きが取れなくなることがあるため、
# 必ずこのPWA会員ページ(自前のモーダルビューアで画像を表示する)を開かせる。
PWA_MEMBER_URL = os.environ.get("PWA_MEMBER_URL", "https://177chart.com/member/").strip()

# 地点・サイクル(00Z/12Zそれぞれ)ごとの連続欠測回数を数え、一定回数を超えたら
# プレースホルダー画像内で目立たせる。配信は12Z回に一本化され1日1回だが、
# 00Z・12Zそれぞれ独立にカウントする(キーは"{地点コード}_00"/"_12")ため、
# 1回=1日として7回=7日間連続欠測が既定の閾値になる。
# カウンタはR2に小さなJSONとして保存し、実行(GitHub Actions)をまたいで引き継ぐ。
NO_DATA_STATE_KEY = "state/no_data_streak.json"
NO_DATA_ALERT_STREAK = int(os.environ.get("EMAGRAM_NO_DATA_ALERT_STREAK", "7"))

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


def target_sounding_times() -> tuple[datetime, datetime]:
    """配信対象の00Z・12Z観測時刻(どちらも実行時点のUTC暦日)を返す。
    12Z配信(UTC 19:00 = 翌04:00JST)に一本化したため、実行時点では
    00Z(19時間経過)・12Z(7時間経過)とも収録済みになっている。
    UTC暦日は00Z(09:00JST)・12Z(21:00JST)ともJST側でも同じ日付になるが、
    配信自体は翌日未明(JST)に行うため、JST視点では「前日まとめ」になる。"""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today, today.replace(hour=12)


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


WXCHART_LOGO_LIGHT_URL = "https://177chart.com/wp-content/uploads/2026/08/logo-light.png"


@functools.lru_cache(maxsize=1)
def _fetch_wxchart_logo_bytes():
    try:
        r = requests.get(WXCHART_LOGO_LIGHT_URL, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"[WARN] logo fetch failed ({WXCHART_LOGO_LIGHT_URL}): {e}")
        return None


def fetch_wxchart_logo():
    """クレジット表記(「作成: 177chart」)に添えるロゴマークを取得する。
    プロセス内で最初の1回だけ取得しキャッシュする。失敗時はNone(テキストのみ)。"""
    data = _fetch_wxchart_logo_bytes()
    if data is None:
        return None
    return Image.open(BytesIO(data)).convert("RGBA")


def load_no_data_streaks() -> dict[str, int]:
    """地点ごとの連続欠測回数をR2から読み込む。無ければ空の辞書。"""
    try:
        raw = get_bytes(NO_DATA_STATE_KEY)
    except Exception as e:
        print(f"[WARN] 欠測カウンタの読み込みに失敗: {e}", file=sys.stderr)
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"[WARN] 欠測カウンタのパースに失敗: {e}", file=sys.stderr)
        return {}


def save_no_data_streaks(streaks: dict[str, int]) -> None:
    """地点ごとの連続欠測回数をR2に保存する。失敗しても配信自体は止めない。"""
    try:
        put_bytes(
            NO_DATA_STATE_KEY,
            json.dumps(streaks, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            cache_control="no-cache",
        )
    except Exception as e:
        print(f"[WARN] 欠測カウンタの保存に失敗: {e}", file=sys.stderr)


def placeholder_image(name: str, dt: datetime, streak: int = 0) -> bytes:
    """データが取得できなかった地点用のプレースホルダー画像。
    連続欠測がNO_DATA_ALERT_STREAK回(既定7回=00Z/12Zそれぞれ1日1回換算で7日分)
    以上続いている場合は「欠測継続 要調査」を表示して目立たせる。"""
    img = Image.new("RGB", (CELL_W, CELL_H), "white")
    draw = ImageDraw.Draw(img)

    font_large = load_font(CJK_BOLD_CANDIDATES, 40)
    font_small = load_font(CJK_REGULAR_CANDIDATES, 24)

    if streak >= NO_DATA_ALERT_STREAK:
        days = streak
        lines = [
            ("⚠ 欠測継続 要調査", font_large),
            (f"約{days}日間データなし", font_small),
            (f"{dt.strftime('%Y-%m-%d %H')}Z", font_small),
        ]
        text_color = "red"
    else:
        lines = [
            ("データなし", font_large),
            (f"{dt.strftime('%Y-%m-%d %H')}Z", font_small),
        ]
        text_color = "black"

    total_h = sum(draw.textbbox((0, 0), t, font=f)[3] for t, f in lines) + 20 * (len(lines) - 1)
    y = (CELL_H - total_h) // 2
    for text, font in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((CELL_W - w) // 2, y), text, fill=text_color, font=font)
        y += (bbox[3] - bbox[1]) + 20

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


RETRY_COUNT = 3
RETRY_WAIT_SECONDS = 180


def fetch_image_with_fallback(stnm: str, name: str, dt: datetime, streak: int) -> tuple[bytes, bool]:
    """当該時刻の画像を確保する。無ければプレースホルダー。
    地点間で時系列がずれるのを避けるため、前回観測への遡りはしない。
    一部地点はサーバー側の反映が観測から数時間後にずれ込むことがあるため、
    取得できない場合は少し待って数回リトライしてから諦める。
    戻り値: (画像bytes, データ取得に成功したか)"""
    img_bytes = fetch_image(stnm, dt)
    if img_bytes:
        return img_bytes, True

    for attempt in range(1, RETRY_COUNT + 1):
        print(f"RETRY {attempt}/{RETRY_COUNT}: {name} を{RETRY_WAIT_SECONDS}秒後に再試行します")
        time.sleep(RETRY_WAIT_SECONDS)
        img_bytes = fetch_image(stnm, dt)
        if img_bytes:
            print(f"RETRY OK: {name}")
            return img_bytes, True

    new_streak = streak + 1
    print(f"NO DATA: {name} はプレースホルダーを使用（連続{new_streak}回目)")
    return placeholder_image(name, dt, new_streak), False


PAIR_COLS = 3
PAIR_ROWS = 5
PAIR_INNER_GAP = 3     # 同じ地点の00Z/12Zペア内の余白(さらに半分に)
PAIR_GROUP_GAP = 144   # 隣の地点(ペア)との余白(現在の1.5倍に)

# Wyoming大学自身が図の右下に焼き込んでいる"University of Wyoming
# Atmospheric Science"のクレジット行の高さ。ペアで2回(00Z/12Z)重複して
# 出るため、00Z側だけ塗りつぶして消し、12Z側の1回だけ残す。
WYOMING_CREDIT_BAND_H = 25

# 生画像(800x640)は、地点・時刻によらず絵柄の左右に約20pxの白余白が
# 一定して付く(軸の範囲が固定のテンプレートのため)。00Z側の右余白・
# 12Z側の左余白をこの分だけ切り詰め、00Zの絵柄の右端と12Zの
# タイトル("Station...")の左端がほぼ密着するようにする。
CELL_SIDE_TRIM = 20
TRIMMED_CELL_W = CELL_W - CELL_SIDE_TRIM


def build_grid_image(stations_with_pairs: list) -> bytes:
    """15地点分を、各地点00Z/12Zの2枚組×3列5段のグリッド画像に結合する。
    地点名ラベルはペアにつき1つだけ(00Z側の上、左上寄せ)。
    stations_with_pairs: [(name, img00_bytes, img12_bytes), ...]"""
    pair_w = TRIMMED_CELL_W * 2 + PAIR_INNER_GAP
    pair_h = LABEL_H + CELL_H
    canvas_w = PAIR_COLS * pair_w + (PAIR_COLS - 1) * PAIR_GROUP_GAP
    canvas_h = PAIR_ROWS * pair_h + (PAIR_ROWS - 1) * PAIR_GROUP_GAP
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    font = load_font(CJK_BOLD_CANDIDATES, 32)

    for idx, (name, img00_bytes, img12_bytes) in enumerate(stations_with_pairs):
        col = idx % PAIR_COLS
        row = idx // PAIR_COLS
        x0 = col * (pair_w + PAIR_GROUP_GAP)
        y0 = row * (pair_h + PAIR_GROUP_GAP)

        bbox = draw.textbbox((0, 0), name, font=font)
        th = bbox[3] - bbox[1]
        draw.text((x0, y0 + (LABEL_H - th) // 2), name, fill="black", font=font)

        for i, img_bytes in enumerate((img00_bytes, img12_bytes)):
            with Image.open(BytesIO(img_bytes)) as im:
                rgb = im.convert("RGB")
                if rgb.size != (CELL_W, CELL_H):
                    rgb = rgb.resize((CELL_W, CELL_H), Image.Resampling.LANCZOS)
                if i == 0:
                    rgb = rgb.copy()
                    ImageDraw.Draw(rgb).rectangle(
                        [0, CELL_H - WYOMING_CREDIT_BAND_H, CELL_W, CELL_H], fill="white"
                    )
                    rgb = rgb.crop((0, 0, TRIMMED_CELL_W, CELL_H))
                else:
                    rgb = rgb.crop((CELL_SIDE_TRIM, 0, CELL_W, CELL_H))
                px = x0 + i * (TRIMMED_CELL_W + PAIR_INNER_GAP)
                canvas.paste(rgb, (px, y0 + LABEL_H))

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def caption_text_for(dt: datetime) -> str:
    return (
        f"作成日時: {dt.strftime('%Y年%m月%d日 %H:%M')} UTC"
        "　出典: University of Wyoming 高層観測アーカイブ (weather.arcc.uwyo.edu)"
        "　作成: 177chart"
    )


def _wrap_caption_lines(text: str, font, available_w: int, tmp_draw) -> list:
    """"　"区切りの単位で、収まる範囲まで貪欲に行を詰める。"""
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


CAPTION_LOGO_MARKER = "作成: 177chart"
_LOGO_AUTO = object()  # logo_img省略時、自動取得させる目印


def _draw_caption_line(draw, bar, line, font, x_right, y, bbox, logo_img, fill=(90, 90, 90)):
    """1行分のキャプションをx_right(右端)に合わせて描く。logo_img指定時、
    行内の"作成: 177chart"の位置だけロゴマークを挟んで描く
    (大きさは行の文字の上端・下端に合わせる)。"""
    idx = line.find(CAPTION_LOGO_MARKER) if logo_img is not None else -1
    if idx < 0:
        w = draw.textbbox((0, 0), line, font=font)[2]
        draw.text((x_right - w, y - bbox[1]), line, fill=fill, font=font)
        return

    before = line[:idx]
    after = line[idx + len(CAPTION_LOGO_MARKER):]
    prefix, suffix = "作成: ", "177chart"

    before_w = draw.textbbox((0, 0), before, font=font)[2] if before else 0
    prefix_w = draw.textbbox((0, 0), prefix, font=font)[2]
    suffix_w = draw.textbbox((0, 0), suffix, font=font)[2]
    after_w = draw.textbbox((0, 0), after, font=font)[2] if after else 0

    text_top = y - bbox[1]
    logo_h = max(1, bbox[3] - bbox[1])
    logo_w = max(1, round(logo_img.width * logo_h / logo_img.height))
    gap = max(2, logo_h // 8)

    total_w = before_w + prefix_w + gap + logo_w + gap + suffix_w + after_w
    x = x_right - total_w

    if before:
        draw.text((x, text_top), before, fill=fill, font=font)
    x += before_w
    draw.text((x, text_top), prefix, fill=fill, font=font)
    x += prefix_w + gap
    logo_resized = logo_img.resize((logo_w, logo_h), Image.LANCZOS)
    bar.paste(logo_resized, (x, text_top), logo_resized)
    x += logo_w + gap
    draw.text((x, text_top), suffix, fill=fill, font=font)
    x += suffix_w
    if after:
        draw.text((x, text_top), after, fill=fill, font=font)


def append_caption_bar(
    img_bytes: bytes,
    dt: datetime,
    *,
    font_size: int = 26,
    pad: int = 14,
    align: str = "right",
    min_font_size: int = 14,
    logo_img=_LOGO_AUTO,
) -> bytes:
    """画像の下に、作成日時(UTC)・出典を記した余白バー(既定で右寄せ)を追加する。
    横幅が足りない場合(サムネイル等)は、まず複数行に折り返す。それでも
    収まらない極端に狭い場合だけ、可読性を保てるmin_font_sizeを下限に
    フォントを縮小する。"作成: 177chart"の部分にはロゴマークをインラインで
    挟んで描く(logo_img省略時は自動取得、明示的にNoneを渡せばロゴ無し)。"""
    if logo_img is _LOGO_AUTO:
        logo_img = fetch_wxchart_logo()
    text = caption_text_for(dt)

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
        x_right = (rgb.width - pad) if align == "right" else (pad + w)
        _draw_caption_line(draw, canvas, ln, font, x_right, y, bbox, logo_img)
        y += line_h + line_gap

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumbnail(img_bytes: bytes, dt: datetime, *, baked_font_size: int = 26, thumb_font_size: int = 20) -> bytes:
    """
    Discordサムネイルを作る。焼き込み済みの出典バー(4000px基準の等倍フォント)は
    縮小すると潰れて読めなくなるため、いったん取り除き、縮小後の解像度に
    合わせた読めるサイズで描き直す。
    """
    baked_font = load_font(CJK_REGULAR_CANDIDATES, baked_font_size)
    tmp = Image.new("RGB", (10, 10), "white")
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), caption_text_for(dt), font=baked_font)
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
        rgb_bytes = append_caption_bar(buf.getvalue(), dt, font_size=thumb_font_size, pad=10)

    with Image.open(BytesIO(rgb_bytes)) as im2:
        out = BytesIO()
        im2.convert("RGB").save(out, format="JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
        return out.getvalue()


WYOMING_PORTAL_URL = "https://weather.arcc.uwyo.edu/upperair/"


def build_content(dt: datetime, highres_url: str) -> str:
    return (
        f"高層観測データ　{dt.strftime('%Y/%m/%d')}まとめ\n"
        f"エマグラム 前日まとめ（{len(STATIONS)}地点）\n"
        f"🔗 [University of Wyoming 高層観測アーカイブ](<{WYOMING_PORTAL_URL}>)\n"
        f"📥 [高解像度PNGをダウンロード（{R2_RETENTION_DAYS}日間有効）](<{highres_url}>)"
    )


def notify_dm_subscribers(
    content: str, thumb_bytes: bytes, highres_url: str, dt: datetime, size_bytes: int = 0
) -> None:
    """有料購読者（Notion管理）へ、公開チャンネルと同じ内容を配信する。
    Discord経由の購読者にはDM、PWA/メールログイン経由の購読者には
    OneSignal Web Pushを送る。"""
    try:
        discord_ids = get_active_discord_ids()
    except Exception as e:
        print(f"[WARN] DM購読者リスト取得失敗: {e}")
        discord_ids = []

    if discord_ids and DISCORD_DM_ENABLE:
        send_dm_to_all(discord_ids, content, thumb_bytes, "emagram_thumb.jpg")

    try:
        emails = get_active_emails()
    except Exception as e:
        print(f"[WARN] Push購読者リスト取得失敗: {e}")
        emails = []

    if emails:
        try:
            send_push_to_all(emails, "エマグラム", "新しいエマグラムが届きました", url=PWA_MEMBER_URL)
        except Exception as e:
            print(f"[WARN] OneSignal push送信失敗: {e}")

    issue_time_label = f"高層観測データ　{dt.strftime('%Y/%m/%d')}まとめ"
    record_recent_item(
        f"エマグラム（{len(STATIONS)}地点）", highres_url, "エマグラム", issue_time_label, size_bytes=size_bytes
    )


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

    dt00, dt12 = target_sounding_times()

    streaks = load_no_data_streaks()
    stations_with_pairs = []
    for stnm, name in STATIONS:
        img00, ok00 = fetch_image_with_fallback(stnm, name, dt00, streaks.get(f"{stnm}_00", 0))
        streaks[f"{stnm}_00"] = 0 if ok00 else streaks.get(f"{stnm}_00", 0) + 1
        img12, ok12 = fetch_image_with_fallback(stnm, name, dt12, streaks.get(f"{stnm}_12", 0))
        streaks[f"{stnm}_12"] = 0 if ok12 else streaks.get(f"{stnm}_12", 0) + 1
        stations_with_pairs.append((name, img00, img12))
    save_no_data_streaks(streaks)

    combined = build_grid_image(stations_with_pairs)
    # キャプション・投稿本文・PWA履歴はいずれも12Z(配信を一本化した基準サイクル)を代表値にする。
    combined = append_caption_bar(combined, dt12)

    # 同じUTC暦日に複数回実行される(手動再実行等)と同じR2キーになってしまうため、
    # 実際の実行時刻(HHMMSS, UTC)を付けてキーを一意にする。
    now_utc = datetime.now(timezone.utc)
    r2_key = f"{dt00.strftime('%Y%m%d')}_{now_utc.strftime('%H%M%S')}.png"
    put_bytes(r2_key, combined, content_type="image/png")
    highres_url = make_url(r2_key)
    print(f"R2 UPLOADED: {highres_url}")

    thumb = make_thumbnail(combined, dt12)

    if post_combined(webhook_url, dt12, thumb, highres_url):
        print("POSTED")
        notify_dm_subscribers(build_content(dt12, highres_url), thumb, highres_url, dt12, size_bytes=len(combined))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
