# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# JMA 公開天気予報 → Pillow PNG → Discord
# データソース: bosai/forecast/data/forecast/050000.json（認証不要）
#
# 出力:
#   [1] 市町村天気一覧（全25市町村 × 今日/明日 天気・気温）
#   [2] 短期予報（今日/明日/明後日 × 沿岸/内陸 天気・降水確率・気温）
#   [3] 週間予報（7日間 天気・降水確率・信頼度・最高最低気温）
# =============================================================================

from __future__ import annotations

import io
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# =============================================================================
# 設定
# =============================================================================
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/050000.json"
JMA_FORECAST_PORTAL = (
    "https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code=050000"
)
DISCORD_GUIDANCE_WEBHOOK_URL = os.environ.get("DISCORD_GUIDANCE_WEBHOOK_URL", "")

WCN_KISHO_URL = "https://www.weathercaster.jp/member/member_only/kisho_shiryo/"

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX  = os.environ.get("R2_PREFIX", "guidance").strip().strip("/")

JST = timezone(timedelta(hours=9))
WDAYS = "月火水木金土日"

COAST_CODE  = "050010"
INLAND_CODE = "050020"
PREF_CODE   = "050000"

AREA_LABELS    = {COAST_CODE: "沿岸", INLAND_CODE: "内陸", PREF_CODE: "秋田県"}
RELIABILITY_JP = {"A": "高", "B": "中", "C": "低"}

# 短期予報の温度代表地点
STATION_LABELS = {"32402": "秋田", "32126": "鷹巣", "32596": "横手"}

# 秋田県 市町村一覧（予報地域, 気温代表観測点）
#   予報地域: COAST_CODE=沿岸 / INLAND_CODE=内陸
#   気温代表: 32402=秋田 / 32126=鷹巣 / 32596=横手
AKITA_MUNICIPALITIES: List[Tuple[str, str, str]] = [
    # 沿岸
    ("秋田市",    COAST_CODE, "32402"),
    ("潟上市",    COAST_CODE, "32402"),
    ("男鹿市",    COAST_CODE, "32402"),
    ("五城目町",  COAST_CODE, "32402"),
    ("八郎潟町",  COAST_CODE, "32402"),
    ("井川町",    COAST_CODE, "32402"),
    ("大潟村",    COAST_CODE, "32402"),
    ("能代市",    COAST_CODE, "32402"),
    ("三種町",    COAST_CODE, "32402"),
    ("八峰町",    COAST_CODE, "32402"),
    ("由利本荘市",COAST_CODE, "32402"),
    ("にかほ市",  COAST_CODE, "32402"),
    # 内陸
    ("大館市",    INLAND_CODE, "32126"),
    ("小坂町",    INLAND_CODE, "32126"),
    ("北秋田市",  INLAND_CODE, "32126"),
    ("上小阿仁村",INLAND_CODE, "32126"),
    ("藤里町",    INLAND_CODE, "32126"),
    ("鹿角市",    INLAND_CODE, "32126"),
    ("仙北市",    INLAND_CODE, "32596"),
    ("大仙市",    INLAND_CODE, "32596"),
    ("横手市",    INLAND_CODE, "32596"),
    ("湯沢市",    INLAND_CODE, "32596"),
    ("美郷町",    INLAND_CODE, "32596"),
    ("羽後町",    INLAND_CODE, "32596"),
    ("東成瀬村",  INLAND_CODE, "32596"),
]

# 画像スタイル
C_TITLE_BG  = (45,  90, 145)
C_TITLE_FG  = (255, 255, 255)
C_HEADER_BG = (85, 140, 200)
C_HEADER_FG = (255, 255, 255)
C_ROW_ODD   = (255, 255, 255)
C_ROW_EVEN  = (238, 246, 255)
C_BORDER    = (190, 205, 220)
C_TEXT      = (30,  30,  30)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# =============================================================================
# ユーティリティ
# =============================================================================

def _jst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def _jst(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except ValueError:
        return None


def _day_label(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}({WDAYS[dt.weekday()]})"


def _v(arr: list, i: int, default: str = "-") -> str:
    return arr[i] if i < len(arr) and arr[i] else default


# =============================================================================
# フォント
# =============================================================================

def _load_fonts():
    try:
        from PIL import ImageFont
        for path in FONT_CANDIDATES:
            if os.path.exists(path):
                try:
                    f_sm = ImageFont.truetype(path, 13)
                    f_md = ImageFont.truetype(path, 14)
                    f_lg = ImageFont.truetype(path, 15)
                    print(f"[INFO] font: {path}")
                    return f_sm, f_md, f_lg
                except Exception:
                    pass
        f = ImageFont.load_default()
        return f, f, f
    except ImportError:
        return None, None, None


# =============================================================================
# HTTP
# =============================================================================

def _fetch(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "akita-guidance-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] fetch {url}: {e}")
        return None


# =============================================================================
# 予報データ解析
# =============================================================================

def _parse_short_term(short: dict) -> dict:
    ts = short.get("timeSeries", [])
    if len(ts) < 3:
        return {}

    t0 = ts[0]  # 天気
    weather_times = [_jst(t) for t in t0.get("timeDefines", [])]
    weather_times = [dt for dt in weather_times if dt]
    weather_by_area = {a["area"]["code"]: a for a in t0.get("areas", [])}

    t1 = ts[1]  # 降水確率
    pop_times = [_jst(t) for t in t1.get("timeDefines", [])]
    pop_times = [dt for dt in pop_times if dt]
    pops_by_area = {a["area"]["code"]: a for a in t1.get("areas", [])}

    t2 = ts[2]  # 気温
    temps_by_station = {a["area"]["code"]: a for a in t2.get("areas", [])}

    return {
        "office":         short.get("publishingOffice", ""),
        "report_dt":      _jst(short.get("reportDatetime", "")),
        "weather_times":  weather_times,
        "weather":        weather_by_area,
        "pop_times":      pop_times,
        "pops":           pops_by_area,
        "temps":          temps_by_station,
    }


def _parse_weekly(weekly: dict) -> dict:
    ts = weekly.get("timeSeries", [])
    if len(ts) < 2:
        return {}

    t0 = ts[0]
    week_times = [_jst(t) for t in t0.get("timeDefines", [])]
    week_times = [dt for dt in week_times if dt]
    area0 = t0.get("areas", [{}])[0]

    t1 = ts[1]
    temp_area = t1.get("areas", [{}])[0]

    avg_areas = weekly.get("tempAverage", {}).get("areas", [{}])
    avg_area  = avg_areas[0] if avg_areas else {}

    return {
        "office":         weekly.get("publishingOffice", ""),
        "report_dt":      _jst(weekly.get("reportDatetime", "")),
        "week_times":     week_times,
        "weather_codes":  area0.get("weatherCodes", []),
        "weathers":       area0.get("weathers",     []),
        "pops":           area0.get("pops",          []),
        "reliabilities":  area0.get("reliabilities", []),
        "temps_max":      temp_area.get("tempsMax",  []),
        "temps_min":      temp_area.get("tempsMin",  []),
        "avg_max":        avg_area.get("max", []),
        "avg_min":        avg_area.get("min", []),
    }


# =============================================================================
# ヘルパー
# =============================================================================

def _group_pops_by_day(
    pop_times: List[datetime],
    vals: List[str],
    weather_days: List[datetime],
) -> List[str]:
    """降水確率 6スロットを 天気の日単位にまとめる。"""
    result = []
    for day_dt in weather_days:
        day_date = day_dt.date()
        slots = [v for pt, v in zip(pop_times, vals) if pt.date() == day_date]
        result.append("/".join(f"{v}%" for v in slots) if slots else "-")
    return result


def _shorten_weather(text: str, max_len: int = 12) -> str:
    text = (text
            .replace("のち", "後")
            .replace("時々", "時")
            .replace("一時", "一")
            .replace("所により", "")
            .replace("激しく", "強"))
    return text[:max_len] if len(text) > max_len else text


def _shorten_wind(text: str, max_len: int = 8) -> str:
    return text[:max_len] if text and len(text) > max_len else (text or "-")


def _anomaly(val_str: str, avg_val: str) -> str:
    try:
        diff = round(float(val_str) - float(avg_val))
        return f"+{diff}" if diff > 0 else str(diff) if diff != 0 else "±0"
    except (TypeError, ValueError):
        return ""


# =============================================================================
# Pillow テーブル描画（amedas.py 共通パターン）
# =============================================================================

def _cell_w(draw, texts: List[str], font, pad: int = 16) -> int:
    max_w = 0
    for t in texts:
        bb = draw.textbbox((0, 0), t, font=font)
        max_w = max(max_w, bb[2] - bb[0])
    return max_w + pad


def _draw_table_img(
    title: str,
    headers: List[str],
    rows: List[List[str]],
    right_align_cols: set = None,
) -> bytes:
    from PIL import Image, ImageDraw
    right_align_cols = right_align_cols or set()

    tmp = Image.new("RGB", (1, 1))
    d0  = ImageDraw.Draw(tmp)
    f_sm, f_md, f_lg = _load_fonts()
    if f_sm is None:
        raise ImportError("Pillow not available")

    ROW_H = 26
    HDR_H = 28
    TTL_H = 32
    PAD_X = 10

    col_contents = [
        [h] + [r[i] for r in rows if i < len(r)]
        for i, h in enumerate(headers)
    ]
    col_widths = [_cell_w(d0, col, f_sm) for col in col_contents]
    total_w = sum(col_widths) + len(col_widths) + 1
    total_h = TTL_H + HDR_H + len(rows) * ROW_H + 1

    img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    d   = ImageDraw.Draw(img)

    d.rectangle([(0, 0), (total_w, TTL_H)], fill=C_TITLE_BG)
    d.text((PAD_X, (TTL_H - 15) // 2), title, fill=C_TITLE_FG, font=f_lg)

    y = TTL_H
    d.rectangle([(0, y), (total_w, y + HDR_H)], fill=C_HEADER_BG)
    x = 0
    for hdr, cw in zip(headers, col_widths):
        bb = d.textbbox((0, 0), hdr, font=f_sm)
        tw = bb[2] - bb[0]
        d.text((x + (cw - tw) // 2, y + (HDR_H - 13) // 2), hdr, fill=C_HEADER_FG, font=f_sm)
        x += cw + 1
    y += HDR_H

    for ri, row in enumerate(rows):
        bg = C_ROW_ODD if ri % 2 == 0 else C_ROW_EVEN
        d.rectangle([(0, y), (total_w, y + ROW_H)], fill=bg)
        d.line([(0, y), (total_w, y)], fill=C_BORDER)
        x = 0
        for ci, (cell, cw) in enumerate(zip(row, col_widths)):
            bb = d.textbbox((0, 0), cell, font=f_sm)
            tw = bb[2] - bb[0]
            tx = x + cw - tw - 6 if ci in right_align_cols else x + 6
            d.text((tx, y + (ROW_H - 13) // 2), cell, fill=C_TEXT, font=f_sm)
            x += cw + 1
        y += ROW_H

    x = 0
    for cw in col_widths[:-1]:
        x += cw
        d.line([(x, TTL_H), (x, total_h)], fill=C_BORDER)
        x += 1
    d.line([(0, total_h - 1), (total_w, total_h - 1)], fill=C_BORDER)
    d.rectangle([(0, 0), (total_w - 1, total_h - 1)], outline=C_BORDER)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# =============================================================================
# [1] 市町村天気一覧
# =============================================================================

def build_municipality_img(st: dict) -> Optional[bytes]:
    """市町村 × 今日/明日 天気・気温 テーブル。"""
    if not st:
        return None

    report_dt     = st.get("report_dt")
    weather_times = st.get("weather_times", [])
    if len(weather_times) < 2:
        return None

    today_dt  = weather_times[0]
    tmrw_dt   = weather_times[1] if len(weather_times) > 1 else None

    today_lbl = f"今日({_day_label(today_dt)})"
    tmrw_lbl  = f"明日({_day_label(tmrw_dt)})" if tmrw_dt else "明日"

    ts_str = report_dt.strftime("%Y/%m/%d %H:%M") if report_dt else ""
    title  = f"秋田県 市町村天気一覧  {ts_str} JST"

    headers = ["市町村", "地域", today_lbl + " 天気", tmrw_lbl + " 天気",
               "今日最高℃", "今日最低℃", "明日最高℃", "明日最低℃"]

    rows = []
    for muni_name, area_code, sta_code in AKITA_MUNICIPALITIES:
        area_a  = st["weather"].get(area_code, {})
        weathers = area_a.get("weathers", [])
        temp_a  = st["temps"].get(sta_code, {})
        temps   = temp_a.get("temps", [])  # [today_max, today_min, tmrw_max, tmrw_min]

        today_w = _shorten_weather(_v(weathers, 0))
        tmrw_w  = _shorten_weather(_v(weathers, 1))

        rows.append([
            muni_name,
            AREA_LABELS.get(area_code, area_code),
            today_w,
            tmrw_w,
            _v(temps, 0),   # today max
            _v(temps, 1),   # today min
            _v(temps, 2),   # tmrw max
            _v(temps, 3),   # tmrw min
        ])

    try:
        return _draw_table_img(title, headers, rows, right_align_cols={4, 5, 6, 7})
    except Exception as e:
        print(f"[ERR] municipality img: {e}")
        return None


# =============================================================================
# [2] 短期予報
# =============================================================================

def build_tanki_img(st: dict) -> Optional[bytes]:
    """短期予報（今日/明日/明後日）テーブル。"""
    if not st:
        return None

    report_dt     = st.get("report_dt")
    weather_times = st.get("weather_times", [])
    if not weather_times:
        return None

    office = st.get("office", "")
    ts_str = report_dt.strftime("%Y/%m/%d %H:%M") if report_dt else ""
    title  = f"秋田県 短期天気予報  {ts_str} JST  発表: {office}"

    day_labels = ["今日", "明日", "明後日"]
    day_hdrs = [
        f"{day_labels[i] if i < len(day_labels) else f'+{i}日'}({_day_label(dt)})"
        for i, dt in enumerate(weather_times[:3])
    ]
    headers = [""] + day_hdrs
    rows    = []

    # 天気・風
    for code, label in [(COAST_CODE, "沿岸"), (INLAND_CODE, "内陸")]:
        a        = st["weather"].get(code, {})
        weathers = a.get("weathers", [])
        winds    = a.get("winds",    [])

        rows.append(
            [f"{label} 天気"] + [
                _shorten_weather(_v(weathers, i)) for i in range(len(weather_times[:3]))
            ]
        )
        rows.append(
            [f"{label} 風"] + [
                _shorten_wind(_v(winds, i)) for i in range(len(weather_times[:3]))
            ]
        )

    # 降水確率
    for code, label in [(COAST_CODE, "沿岸"), (INLAND_CODE, "内陸")]:
        pop_a    = st["pops"].get(code, {})
        pop_vals = pop_a.get("pops", [])
        pop_days = _group_pops_by_day(st["pop_times"], pop_vals, weather_times[:3])
        rows.append([f"降水確率%({label})"] + pop_days)

    # 気温
    for code, label in STATION_LABELS.items():
        t_a   = st["temps"].get(code, {})
        temps = t_a.get("temps", [])
        # temps = [今日最高, 今日最低, 明日最高, 明日最低]
        today_str = (f"↑{temps[0]} ↓{temps[1]}" if len(temps) >= 2
                     else f"↑{temps[0]}" if temps else "-")
        tmrw_str  = (f"↑{temps[2]} ↓{temps[3]}" if len(temps) >= 4
                     else f"↑{temps[2]}" if len(temps) >= 3 else "-")
        rows.append([f"気温℃ {label}", today_str, tmrw_str, "-"])

    try:
        return _draw_table_img(title, headers, rows)
    except Exception as e:
        print(f"[ERR] tanki img: {e}")
        return None


# =============================================================================
# [3] 週間予報
# =============================================================================

def build_shuukan_img(wk: dict) -> Optional[bytes]:
    """週間予報（7日間）テーブル。"""
    if not wk:
        return None

    report_dt  = wk.get("report_dt")
    week_times = wk.get("week_times", [])
    if not week_times:
        return None

    office = wk.get("office", "")
    ts_str = report_dt.strftime("%Y/%m/%d %H:%M") if report_dt else ""
    title  = f"秋田県 週間天気予報  {ts_str} JST  発表: {office}"

    headers = [""] + [_day_label(dt) for dt in week_times]
    n       = len(week_times)

    weathers     = wk.get("weathers",     [])
    weather_codes = wk.get("weather_codes", [])
    pops         = wk.get("pops",         [])
    rels         = wk.get("reliabilities", [])
    temps_max    = wk.get("temps_max",    [])
    temps_min    = wk.get("temps_min",    [])
    avg_max      = wk.get("avg_max",      [])
    avg_min      = wk.get("avg_min",      [])

    rows = [
        ["秋田県 天気"] + [
            _shorten_weather(_v(weathers, i)) for i in range(n)
        ],
        ["天気コード"] + [
            f"[{_v(weather_codes, i)}]" for i in range(n)
        ],
        ["降水確率%"] + [
            f"{_v(pops, i)}%" if _v(pops, i) != "-" else "-"
            for i in range(n)
        ],
        ["信頼度"] + [
            RELIABILITY_JP.get(_v(rels, i), _v(rels, i)) for i in range(n)
        ],
        ["秋田 最高℃"] + [
            (f"{_v(temps_max, i)}"
             + (f"({_anomaly(_v(temps_max, i), _v(avg_max, i))})"
                if i < len(avg_max) and _v(avg_max, i) != "-" else ""))
            for i in range(n)
        ],
        ["秋田 最低℃"] + [
            (f"{_v(temps_min, i)}"
             + (f"({_anomaly(_v(temps_min, i), _v(avg_min, i))})"
                if i < len(avg_min) and _v(avg_min, i) != "-" else ""))
            for i in range(n)
        ],
    ]

    try:
        return _draw_table_img(title, headers, rows, right_align_cols={0})
    except Exception as e:
        print(f"[ERR] shuukan img: {e}")
        return None


# =============================================================================
# R2 アップロード
# =============================================================================

def _upload_r2(items: List[Tuple[str, bytes]]) -> List[str]:
    """(filename, bytes) リストを R2 にアップして URL リストを返す。"""
    if not R2_ENABLE:
        return []
    try:
        from module.utils.r2_utils import put_bytes, make_url
    except ImportError:
        print("[WARN] r2_utils not available")
        return []

    day  = _jst_now().strftime("%Y%m%d")
    urls: List[str] = []
    for fname, data in items:
        key = f"{R2_PREFIX}/{day}/{fname}"
        try:
            put_bytes(key, data, content_type="image/png")
            urls.append(make_url(key))
            print(f"[OK] R2 upload: {key}")
        except Exception as e:
            print(f"[WARN] R2 upload {key}: {e}")
            urls.append("")
    return urls


# =============================================================================
# Notion 書き込み
# =============================================================================

def _notion_write(
    title: str,
    r2_urls: List[str],
    report_dt: Optional[datetime],
) -> None:
    try:
        from module.utils.notion_utils import (
            notion_enabled,
            create_db_row,
            append_images,
            append_heading,
            append_bookmark,
        )
    except ImportError:
        print("[WARN] notion_utils not available")
        return

    if not notion_enabled():
        print("[SKIP] Notion not enabled")
        return

    import time
    init_jst_iso = (report_dt or _jst_now()).isoformat()
    page_id = create_db_row(
        title=title,
        category="Guidance",
        init_jst_iso=init_jst_iso,
        memo="",
        rjtd="",
        prefix=R2_PREFIX,
        r2_url=next((u for u in r2_urls if u), ""),
        autogen=True,
        icon_emoji="🌤️",
    )
    if not page_id:
        print("[WARN] Notion page create failed")
        return

    time.sleep(1.0)

    try:
        valid_urls = [u for u in r2_urls if u]
        if valid_urls:
            append_images(page_id, valid_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] Notion image append failed: {e}")

    try:
        append_heading(page_id, "参考リンク", level=2)
        append_bookmark(page_id, JMA_FORECAST_PORTAL,
                        caption="気象庁 天気予報（秋田県）")
        append_bookmark(page_id, WCN_KISHO_URL,
                        caption="WCN 各種気象情報")
    except Exception as e:
        print(f"[WARN] Notion bookmarks failed: {e}")

    print(f"[OK] Notion page: {page_id}")


# =============================================================================
# Discord 投稿
# =============================================================================

def _post_text(content: str) -> None:
    """テキストのみの Discord メッセージを送る。"""
    if not DISCORD_GUIDANCE_WEBHOOK_URL:
        return
    body = json.dumps({"content": content}).encode("utf-8")
    req  = urllib.request.Request(
        DISCORD_GUIDANCE_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "akita-guidance-bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[OK] Discord text HTTP {r.status}")
    except Exception as e:
        print(f"[ERR] Discord text: {e}")


def _post_image(image_bytes: bytes, filename: str, content: str = ""):
    if not DISCORD_GUIDANCE_WEBHOOK_URL:
        print(f"[SKIP] DISCORD_GUIDANCE_WEBHOOK_URL not set")
        return

    boundary = "----GuidanceBotBoundaryAk1x"
    crlf     = b"\r\n"

    def part_json(data: str) -> bytes:
        hdr = (f"--{boundary}\r\n"
               f'Content-Disposition: form-data; name="payload_json"\r\n'
               f"Content-Type: application/json\r\n\r\n")
        return hdr.encode() + data.encode() + crlf

    def part_file(data: bytes, name: str) -> bytes:
        hdr = (f"--{boundary}\r\n"
               f'Content-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'
               f"Content-Type: image/png\r\n\r\n")
        return hdr.encode() + data + crlf

    body = (part_json(json.dumps({"content": content}))
            + part_file(image_bytes, filename)
            + f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        DISCORD_GUIDANCE_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent":   "akita-guidance-bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[OK] Discord HTTP {r.status} ({filename})")
    except Exception as e:
        print(f"[ERR] Discord post: {e}")


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Guidance (JMA Forecast) ===")

    raw = _fetch(FORECAST_URL)
    if not raw or not isinstance(raw, list):
        print("[ERR] forecast fetch failed")
        return

    short_raw  = raw[0] if len(raw) > 0 else {}
    weekly_raw = raw[1] if len(raw) > 1 else {}

    st = _parse_short_term(short_raw)
    wk = _parse_weekly(weekly_raw)
    report_dt = st.get("report_dt") or wk.get("report_dt")

    # 画像生成
    img1 = build_municipality_img(st)
    img2 = build_tanki_img(st)
    img3 = build_shuukan_img(wk)

    for lbl, img in [("municipality", img1), ("tanki", img2), ("shuukan", img3)]:
        if img:
            print(f"[INFO] {lbl} img: {len(img)} bytes")
        else:
            print(f"[WARN] {lbl} img build failed")

    # R2 アップロード
    img_items = [
        (fn, data)
        for fn, data in [
            ("guidance_municipality.png", img1),
            ("guidance_tanki.png",        img2),
            ("guidance_shuukan.png",      img3),
        ]
        if data
    ]
    r2_urls = _upload_r2(img_items)

    # Notion 書き込み
    ts_str = (report_dt.strftime("%Y/%m/%d %H:%M")
              if report_dt else _jst_now().strftime("%Y/%m/%d %H:%M"))
    _notion_write(f"ガイダンス / {ts_str} JST", r2_urls, report_dt)

    # Discord: 画像投稿
    if img1:
        _post_image(img1, "guidance_municipality.png",
                    content=f"<{JMA_FORECAST_PORTAL}>")
    if img2:
        _post_image(img2, "guidance_tanki.png")
    if img3:
        _post_image(img3, "guidance_shuukan.png")

    # Discord: 参考リンク
    _post_text(
        f"**参考リンク**\n"
        f"・気象庁 天気予報（秋田県）\n{JMA_FORECAST_PORTAL}\n"
        f"・WCN 各種気象情報\n{WCN_KISHO_URL}"
    )

    print("=== Done ===")


if __name__ == "__main__":
    main()
