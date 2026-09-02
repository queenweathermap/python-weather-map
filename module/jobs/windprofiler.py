# -*- coding: utf-8 -*-
#
# module/jobs/windprofiler.py
#
# 気象庁「ウィンドプロファイラ」(WINDAS) 全33地点のチャートを
# 公式ページ (https://www.jma.go.jp/bosai/windprofiler/) から
# Playwrightでスクリーンショットする。1日4回実行し、地点ごとのraw画像を
# 個別にR2へ保存するだけで、Discordへは投稿しない（main()）。
#
# 配信は1日1回、翌日3時JST（前日分の4回が出そろってから）にまとめて行う。
# その日の分を「1地点＝1段、実行分を横に並べる」形の1枚の画像に組み直し、
#   ・既存のjma-windprofilerチャンネルへ通常投稿（DMではない）
#   ・PWA/メールログイン購読者へOneSignal Pushで配信
# の両方を同時に行う（main_daily_stations()）。
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

import functools
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

# 同じ地点の2枚目以降は、単純に横へ並べるのではなく実際の撮影時刻の差分だけ
# ずらして重ねて貼る（2枚目を上に）。ローリングウィンドウの重複部分
# （約1時間強）が2枚目側の絵柄でそのまま上書きされるため、時間軸が
# 継ぎ目なく連続して見える。ずらし幅は実測のPX_PER_HOUR(x軸の目盛り間隔)
# から算出する。撮影間隔は通常6時間おきだが、フォールバックで前日撮影分を
# そのまま使う場合など必ずしも6時間おきとは限らないため、ファイル名の
# 撮影時刻から実際の差分(時間)を計算して使う(build_daily_station_grid内)。
PX_PER_HOUR = 82.5

# チャート本体(プロット領域)のy範囲。各コマは右端まで観測データが埋まって
# いるとは限らず(直近1時間強はまだ未観測で右端が白紙のまま撮影される)、
# この空白部分をそのまま次のコマに繋げると、実データが無いのに目盛り線だけ
# 残った隙間ができてしまう。そのため貼り合わせ時は各コマの「実データの
# 右端」を検出し、そこまでしか貼らないようにする(_panel_data_right_edge)。
PLOT_TOP = STATION_HEADER_HEIGHT
PLOT_BOTTOM = 452

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
    """クレジット表記(「作成：177chart」)に添えるロゴマークを取得する。
    プロセス内で最初の1回だけ取得しキャッシュする。失敗時はNone(テキストのみ)。"""
    data = _fetch_wxchart_logo_bytes()
    if data is None:
        return None
    return Image.open(BytesIO(data)).convert("RGBA")


CAPTION_LOGO_MARKER = "作成：177chart"
_LOGO_AUTO = object()  # append_caption_bar()のlogo_img省略時、自動取得させる目印


def caption_text_for() -> str:
    # 地点コードはURL構成上必須のため、代表として稚内(47406)を指定した状態の
    # ポータルURLを出典として示す(実際の各段は33地点それぞれのデータ)。
    return (
        "出典：気象庁　https://www.jma.go.jp/bosai/windprofiler/#code=47406&type=chart"
        "　提供資料を合成編集　作成：177chart"
    )


def _wrap_caption_lines(text: str, font, available_w: int, tmp_draw) -> list:
    """"　"区切りの単位で、収まる範囲まで貪欲に行を詰める。"""
    segments = text.split("　")
    lines: list = []
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


def _draw_caption_line(draw, bar, line, font, x_right, y, bbox, logo_img, fill=(90, 90, 90)):
    """1行分のキャプションをx_right(右端)に合わせて描く。logo_img指定時、
    行内の"作成：177chart"の位置だけロゴマークを挟んで描く
    (大きさは行の文字の上端・下端に合わせる)。"""
    idx = line.find(CAPTION_LOGO_MARKER) if logo_img is not None else -1
    if idx < 0:
        w = draw.textbbox((0, 0), line, font=font)[2]
        draw.text((x_right - w, y - bbox[1]), line, fill=fill, font=font)
        return

    before = line[:idx]
    after = line[idx + len(CAPTION_LOGO_MARKER):]
    prefix, suffix = "作成：", "177chart"

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
    img: Image.Image,
    text: str,
    *,
    font_size: int = 48,
    pad: int = 24,
    align: str = "right",
    min_font_size: int = 16,
    logo_img=_LOGO_AUTO,
) -> Image.Image:
    """画像の下に、出典を記した余白バー(右寄せ)を追加する。横幅が足りない
    場合はまず複数行に折り返し、それでも収まらなければmin_font_sizeを下限に
    フォントを縮小する。logo_img省略時は「作成：177chart」部分にロゴマーク
    をインラインで自動挿入する(明示的にNoneを渡せばロゴ無し)。"""
    if logo_img is _LOGO_AUTO:
        logo_img = fetch_wxchart_logo()
    img = img.convert("RGB")
    tmp = Image.new("RGB", (10, 10), "white")
    draw_tmp = ImageDraw.Draw(tmp)
    available_w = max(1, img.width - pad * 2)

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

    bar = Image.new("RGB", (img.width, bar_h), "white")
    draw = ImageDraw.Draw(bar)
    y = pad
    for ln, bbox in zip(lines, line_bboxes):
        w = bbox[2] - bbox[0]
        x_right = (img.width - pad) if align == "right" else (pad + w)
        _draw_caption_line(draw, bar, ln, font, x_right, y, bbox, logo_img)
        y += line_h + line_gap

    canvas = Image.new("RGB", (img.width, img.height + bar_h), "white")
    canvas.paste(img, (0, 0))
    canvas.paste(bar, (0, img.height))
    return canvas


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


def _panel_data_right_edge(img: Image.Image, *, left: int) -> int:
    """チャート画像(1コマ)のプロット領域(PLOT_TOP〜PLOT_BOTTOM、x=left以降)を
    右から走査し、観測データ(矢羽根の色つきセル・矢印)がある最も右の列+1を
    返す。全く見つからなければ left を返す(実データ無し)。
    背景の白、および目盛りのうすいグレーの罫線は「データ無し」とみなす。"""
    px = img.convert("RGB").load()
    w = img.width
    for x in range(w - 1, left - 1, -1):
        for y in range(PLOT_TOP, min(PLOT_BOTTOM, img.height)):
            r, g, b = px[x, y]
            # 白背景・グレー罫線(R=G=B に近い明るい色)は無視し、彩度のある色
            # (黄・水色・青)か、黒に近い矢印線だけを「データ」とみなす。
            if (r < 80 and g < 80 and b < 80) or (max(r, g, b) - min(r, g, b) > 15 and max(r, g, b) > 120):
                return x + 1
    return left


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

    # 撮影は当日00:15/06:15/12:15/18:15の4回だが、各コマは撮影時刻を終端とする
    # 約7時間のローリングウィンドウなので、当日00:15のコマは実際にはほぼ前日
    # 17:15〜24:00のデータしか写っていない。dt_jst(対象日)のJST 00:00-24:00を
    # 素直にカバーするには、対象日00:15の代わりに「翌日00:15」(＝対象日
    # 17:15〜24:15をカバーするコマ)を使う必要がある。よって対象日06/12/18時台と
    # 翌日00時台の4コマを選ぶ(実行間隔6時間はここでも変わらないため、
    # 下のx_positions計算はそのまま使える)。
    target_str = dt_jst.strftime("%Y%m%d")
    next_str = (dt_jst + timedelta(days=1)).strftime("%Y%m%d")
    wanted_hours = {target_str: {"06", "12", "18"}, next_str: {"00"}}

    for code, name in STATIONS_ALL:
        target_keys = list(list_keys_with_prefix(f"stations/{code}/{target_str}"))
        candidates = target_keys + list(list_keys_with_prefix(f"stations/{code}/{next_str}"))
        keys = sorted(
            k for k in candidates
            if k.endswith(".png")
            and (hours := wanted_hours.get(k.rsplit("/", 1)[-1][:8])) is not None
            and k.rsplit("/", 1)[-1][8:10] in hours
        )
        if not keys:
            # 翌日00時台のコマがまだ無い等で理想の4コマが揃わない場合、対象日に
            # 撮影できている分だけでも使う(配信自体を落とさないためのフォールバック)。
            keys = sorted(k for k in target_keys if k.endswith(".png"))
        if not keys:
            continue

        panels = []
        panel_times: List[datetime] = []
        data_right_edges: List[int] = []
        for key in keys:
            data = get_bytes(key)
            if data is None:
                continue
            with Image.open(BytesIO(data)) as im:
                rgb = im.convert("RGB")
                if rgb.size != (CELL_W, CELL_H):
                    rgb = rgb.resize((CELL_W, CELL_H), Image.Resampling.LANCZOS)
                panels.append(rgb)
                # クロップ(ヘッダー/軸切り詰め)前に、生画像上での実データ右端を測る
                data_right_edges.append(_panel_data_right_edge(rgb, left=STATION_AXIS_WIDTH))
            ts = key.rsplit("/", 1)[-1].removesuffix(".png")
            panel_times.append(datetime.strptime(ts, "%Y%m%d%H%M").replace(tzinfo=JST))
        if not panels:
            continue

        # 2枚目以降はヘッダー(上)と目盛りラベル(左)を切り詰める(実データ右端も
        # 同じ分だけ左にずれるので合わせて調整する)
        for i in range(1, len(panels)):
            panels[i] = panels[i].crop((STATION_AXIS_WIDTH, STATION_HEADER_HEIGHT, CELL_W, CELL_H))
            data_right_edges[i] -= STATION_AXIS_WIDTH

        # 各パネルのx位置: 1枚目は0起点。2枚目以降は「1枚目のプロット開始位置
        # (STATION_AXIS_WIDTH)」を基準に、実際の撮影時刻の差(前日撮影分の
        # フォールバック使用時など、必ずしも6時間おきとは限らない)分だけ
        # 右にずらした位置に貼る。ローリングウィンドウが約1時間強重なっている
        # ため、この位置に貼ると自然に絵柄が重なり、後から貼る（＝上になる）
        # 2枚目以降の絵柄が優先されて継ぎ目なく見える。
        x_positions = [0] + [
            STATION_AXIS_WIDTH
            + round((panel_times[i] - panel_times[0]).total_seconds() / 3600 * PX_PER_HOUR)
            for i in range(1, len(panels))
        ]

        # 実データの無い右端の空白部分は貼らない(目盛り線だけの隙間ができるのを防ぐ)。
        # 検出に失敗した(0以下や幅超過の)場合は安全側でパネル全体を使う。
        trimmed_panels = []
        for panel, edge in zip(panels, data_right_edges):
            right = edge if 0 < edge <= panel.width else panel.width
            trimmed_panels.append(panel.crop((0, 0, right, panel.height)) if right < panel.width else panel)

        row_h = CELL_H  # 1枚目がヘッダー込みでCELL_Hのため、段の高さはCELL_Hのまま
        row_w = max(x + p.width for x, p in zip(x_positions, trimmed_panels))
        row = Image.new("RGB", (row_w, row_h), "white")
        for x, panel in zip(x_positions, trimmed_panels):
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

    canvas = append_caption_bar(canvas, caption_text_for())

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), len(rows)


def post_daily_station_grid(webhook_url: str, dt_jst: datetime, image_bytes: bytes, url: str) -> bool:
    """既存の購読者向けjma-windprofilerチャンネルへ、前日分の「1地点1段・全実行分
    横並び」グリッドを通常投稿する（DMではなく、main()と同じWebhookを使う）。"""
    content = (
        f"高層観測データ　{dt_jst.strftime('%Y/%m/%d')}まとめ\n"
        f"ウィンドプロファイラ 前日まとめ（{len(STATIONS_ALL)}地点）\n"
        f"🔗 [気象庁 ウィンドプロファイラ（地点別）](<{BASE_URL}>)\n"
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


def notify_pwa_daily_stations(dt_jst: datetime, url: str, station_count: int, size_bytes: int = 0) -> None:
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
        f"高層観測データ {dt_jst.strftime('%Y/%m/%d')}まとめ",
        size_bytes=size_bytes,
    )


def main_daily_stations() -> int:
    """1日1回、翌日3時JSTに実行し、前日分の地点別raw画像を「1地点1段・横並び」の
    1枚のグリッド画像に組み直して、
      ・既存の購読者向けjma-windprofilerチャンネルへ通常投稿（DMではない）
      ・PWA/メールログイン購読者へOneSignal Pushで配信
    の両方を行う。ウィンドプロファイラの配信はこれが唯一（main()は撮影・
    R2保存のみでDiscordへは投稿しない）。"""
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

    notify_pwa_daily_stations(target_jst, url, station_count, size_bytes=len(image_bytes))
    print("NOTIFIED (PWA)")

    return 0 if posted else 1


def main() -> int:
    """1日4回実行し、地点ごとのraw画像をR2へ個別保存するだけ。
    Discordへは投稿しない（前日分は main_daily_stations() が1日1回まとめて配信する）。"""
    dt_jst = _jst_now()

    all_images = screenshot_all_stations()
    upload_station_images(all_images, dt_jst)

    print(f"UPLOADED ({len(all_images)}地点)")
    return 0
