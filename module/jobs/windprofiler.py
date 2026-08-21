# -*- coding: utf-8 -*-
#
# module/jobs/windprofiler.py
#
# 気象庁「ウィンドプロファイラ」(WINDAS) 全33地点のチャートを
# 公式ページ (https://www.jma.go.jp/bosai/windprofiler/) から
# Playwrightでスクリーンショットし、1枚の画像（7列×5行、地点ごとの解像度は
# 変えない）に結合してDiscordへ配信する（main()、1日4回、購読者向け）。
#
# 加えて、実行のたびに地点ごとのraw画像も個別にR2へ保存しておき、1日1回
# （翌日3時JST、前日分が出そろってから）その日の分を「1地点＝1段、実行分を
# 横に並べる」形の1枚の画像に組み直し、
#   ・既存のjma-windprofilerチャンネルへ通常投稿（main()と同じWebhook・DMではない）
#   ・PWA/メールログイン購読者へOneSignal Pushで配信
# の両方を同時に行う（main_daily_stations()）。main()自体（1日4回配信）の
# 内容・頻度は変えない。
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

from module.utils.r2_utils import put_bytes, get_bytes, list_keys_with_prefix, make_url
from module.utils.notion_subscribers import get_active_emails
from module.utils.onesignal_push import send_push_to_all
from module.utils.recent_items import record_recent_item

# プッシュ通知のタップ先。R2の生画像URLに直接飛ばすと、iOSスタンドアロンで
# ツールバー無しの画面のまま身動きが取れなくなることがあるため、モーダル
# ビューア(閉じるボタン付き)を持つ/member/ページに飛ばす
# （weather_map.py / emagram_discord.py と同じ対処）。
PWA_MEMBER_URL = os.environ.get("PWA_MEMBER_URL", "https://177chart.com/member/").strip()

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

GRID_COLS = 7  # 33地点 ÷ 7列 = 5段、最終段が5地点になり8列(最終段1地点のみ)より収まりが良い
CELL_W = 752
CELL_H = 545

# 「1地点＝1段、実行分を横に並べる」画像用: 同じ地点の2枚目以降は地点名・
# 緯度経度・標高のヘッダー(上)と、海抜高度の目盛りラベル(左)を削り、
# くっつくくらいまで詰める（1枚目だけ地点名・目盛りを残す）。
# 実測（#wpr-chart のヘッダー文字～チャート枠、目盛りラベル～チャート枠の
# 罫線位置）に基づく固定値。
STATION_HEADER_HEIGHT = 50
STATION_AXIS_WIDTH = 49

# 同じ地点の並び（上）はほぼ隙間なし、違う地点同士（下記）は
# はっきり区別できるよう、その2倍の余白を空ける。
STATION_GAP = STATION_HEADER_HEIGHT * 2

# 同じ地点の2枚目以降は、単純に横へ並べるのではなく実行間隔(6時間)分だけ
# ずらして重ねて貼る（2枚目を上に）。ローリングウィンドウの重複部分
# （約1時間強）が2枚目側の絵柄でそのまま上書きされるため、時間軸が
# 継ぎ目なく連続して見える。ずらし幅は実測のPX_PER_HOUR(x軸の目盛り間隔)
# から算出する。
RUN_INTERVAL_HOURS = 6
PX_PER_HOUR = 82.5

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


def station_key(code: str, dt_jst: datetime) -> str:
    """地点1件・1回分のraw画像のR2キー（R2_PREFIXは別途自動で付く）。"""
    return f"stations/{code}/{dt_jst.strftime('%Y%m%d%H%M')}.png"


def upload_station_images(all_images: List[Tuple[str, bytes]], dt_jst: datetime) -> None:
    """地点ごとのraw画像を個別にR2へ保存する（1日1回のmain_daily_stations()が
    後でまとめ直すための材料）。購読者向けDiscord配信(main())の成否には
    影響させないよう、失敗しても例外は握りつぶしログのみ出す。"""
    for (code, name), (_name, img_bytes) in zip(STATIONS_ALL, all_images):
        try:
            put_bytes(station_key(code, dt_jst), img_bytes, content_type="image/png")
        except Exception as e:
            print(f"[WARN] {name} ({code}) の個別画像アップロードに失敗: {e}", file=sys.stderr)


def build_daily_station_grid(dt_jst: datetime, *, cols: int = 5) -> Tuple[bytes, int]:
    """
    dt_jstと同じJST日付に撮影された、地点ごとの生画像を集めて
    「1地点＝横一列（その日の全実行分を横に並べる）」にし、
    全地点をcols列のグリッドに並べて1枚の画像にする
    （「全部入り天気図」と同程度の解像度で問題なく扱えている実績があるため、
    分割せず1枚にまとめる）。

    同じ地点の2枚目以降は、地点名・緯度経度・標高のヘッダー(上)と海抜高度の
    目盛りラベル(左)が同じ内容の繰り返しになるため、両方切り詰めてほぼ隙間なく
    詰める（1枚目だけヘッダー・目盛りを残し、どの地点の段か分かるようにする）。
    その代わり、違う地点同士の境目はSTATION_GAP分の余白を空けてはっきり区別する。

    各画像はサイト側のローリングウィンドウ（約7時間分）をそのまま切り出したもので、
    実行間隔(6時間)より長いため隣り合うコマは約1時間分重なる。真に継ぎ目のない
    24時間軸を作るには元データからの再描画が必要だが、それは元データを持たない
    このジョブでは不可能なため、「多少重なりのある複数コマを並べる」方式にする。

    戻り値: (PNGのbytes, 含まれる地点数)
    """
    rows: List[Image.Image] = []

    for code, name in STATIONS_ALL:
        keys = sorted(
            k for k in list_keys_with_prefix(f"stations/{code}/{dt_jst.strftime('%Y%m%d')}")
            if k.endswith(".png")
        )
        if not keys:
            continue

        panels = []
        for key in keys:
            data = get_bytes(key)
            if data is None:
                continue
            with Image.open(BytesIO(data)) as im:
                rgb = im.convert("RGB")
                if rgb.size != (CELL_W, CELL_H):
                    rgb = rgb.resize((CELL_W, CELL_H), Image.Resampling.LANCZOS)
                panels.append(rgb)
        if not panels:
            continue

        # 2枚目以降はヘッダー(上)と目盛りラベル(左)を切り詰める
        for i in range(1, len(panels)):
            panels[i] = panels[i].crop((STATION_AXIS_WIDTH, STATION_HEADER_HEIGHT, CELL_W, CELL_H))

        # 各パネルのx位置: 1枚目は0起点。2枚目以降は「1枚目のプロット開始位置
        # (STATION_AXIS_WIDTH)」を基準に、実行間隔(6時間)分だけ右にずらした
        # 位置に貼る。ローリングウィンドウが約1時間強重なっているため、
        # この位置に貼ると自然に絵柄が重なり、後から貼る（＝上になる）
        # 2枚目以降の絵柄が優先されて継ぎ目なく見える。
        x_positions = [0] + [
            STATION_AXIS_WIDTH + round(i * RUN_INTERVAL_HOURS * PX_PER_HOUR)
            for i in range(1, len(panels))
        ]

        row_h = CELL_H  # 1枚目がヘッダー込みでCELL_Hのため、段の高さはCELL_Hのまま
        row_w = max(x + p.width for x, p in zip(x_positions, panels))
        row = Image.new("RGB", (row_w, row_h), "white")
        for x, panel in zip(x_positions, panels):
            # 2枚目以降はヘッダー分だけ短いので、下端(チャート本体・矢印行)が
            # 1枚目と揃うよう、その分だけ下に寄せて貼る
            row.paste(panel, (x, row_h - panel.height))
        rows.append(row)

    if not rows:
        return b"", 0

    row_w = max(r.width for r in rows)
    grid_rows = ceil(len(rows) / cols)
    canvas_w = row_w * cols + STATION_GAP * (cols - 1)
    canvas_h = CELL_H * grid_rows + STATION_GAP * (grid_rows - 1)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    for idx, row in enumerate(rows):
        col = idx % cols
        grid_row = idx // cols
        x = col * (row_w + STATION_GAP)
        y = grid_row * (CELL_H + STATION_GAP)
        canvas.paste(row, (x, y))

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), len(rows)


def post_daily_station_grid(webhook_url: str, dt_jst: datetime, image_bytes: bytes, url: str) -> bool:
    """既存の購読者向けjma-windprofilerチャンネルへ、前日分の「1地点1段・全実行分
    横並び」グリッドを通常投稿する（DMではなく、main()と同じWebhookを使う）。"""
    content = (
        f"🌀 **ウィンドプロファイラ 前日まとめ（地点別） / {dt_jst.strftime('%Y-%m-%d')}**\n"
        f"1地点＝1段、その日の実行分（最大4回、約1時間ずつ重なりあり）を横に並べています。\n"
        f"📥 [高解像度PNGをダウンロード（{R2_RETENTION_DAYS}日間有効）](<{url}>)"
    )
    payload = {
        "username": "ウィンドプロファイラ（前日まとめ）",
        "content": content,
        "flags": 4,  # SUPPRESS_EMBEDS
    }
    files = {
        "payload_json": (None, json.dumps(payload)),
        "files[0]": ("windprofiler_daily.png", image_bytes, "image/png"),
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


def notify_pwa_daily_stations(dt_jst: datetime, url: str, station_count: int) -> None:
    """PWA/メールログイン購読者へ、前日分のウィンドプロファイラまとめを通知する。
    Discordへの投稿とは独立しており、失敗しても互いに影響しない
    （購読者取得や送信に失敗しても例外は握りつぶし、ログのみ出す）。"""
    try:
        emails = get_active_emails()
    except Exception as e:
        print(f"[WARN] Push購読者リスト取得失敗: {e}")
        emails = []

    if emails:
        try:
            send_push_to_all(
                emails,
                "ウィンドプロファイラ",
                f"前日（{dt_jst.strftime('%m/%d')}）分の高層風まとめが届きました",
                url=PWA_MEMBER_URL,
            )
        except Exception as e:
            print(f"[WARN] OneSignal push送信失敗: {e}")

    record_recent_item(
        f"ウィンドプロファイラ 前日まとめ（{station_count}地点）",
        url,
        "ウィンドプロファイラ",
        f"高層風観測データ {dt_jst.strftime('%Y/%m/%d')}まとめ",
    )


def main_daily_stations() -> int:
    """1日1回、翌日3時JSTに実行し、前日分の地点別raw画像を「1地点1段・横並び」の
    1枚のグリッド画像に組み直して、
      ・既存の購読者向けjma-windprofilerチャンネルへ通常投稿（DMではない）
      ・PWA/メールログイン購読者へOneSignal Pushで配信
    の両方を行う。main()（1日4回の配信）の内容・頻度には影響しない。"""
    webhook_url = os.environ.get("DISCORD_WINDPROFILER_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_WINDPROFILER_WEBHOOK_URL未設定", file=sys.stderr)
        return 1

    # 実行時刻(翌日3時JST)から見て「前日」の分をまとめる
    target_jst = _jst_now() - timedelta(days=1)

    image_bytes, station_count = build_daily_station_grid(target_jst)
    if station_count == 0:
        print("[WARN] 前日分の地点別画像が見つかりませんでした。スキップします")
        return 1

    r2_key = f"{target_jst.strftime('%Y%m%d')}_daily_grid.png"
    put_bytes(r2_key, image_bytes, content_type="image/png")
    url = make_url(r2_key)
    print(f"R2 UPLOADED: {url}")

    posted = post_daily_station_grid(webhook_url, target_jst, image_bytes, url)
    if posted:
        print(f"POSTED ({station_count}地点、1枚)")

    notify_pwa_daily_stations(target_jst, url, station_count)
    print("NOTIFIED (PWA)")

    return 0 if posted else 1


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WINDPROFILER_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_WINDPROFILER_WEBHOOK_URL未設定", file=sys.stderr)
        return 1

    dt_jst = _jst_now()

    all_images = screenshot_all_stations()
    upload_station_images(all_images, dt_jst)

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
