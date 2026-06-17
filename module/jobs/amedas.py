# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# JMA AMeDAS データ → Discord(#amedas) PNG 画像配信
# urllib + Pillow のみ・認証不要・Playwright不使用
#
# 配信: 朝3時 / 午後3時（JST）
# 出力:
#   [1] 秋田県 各局一覧（気温・最高最低・湿度・風速・1h/24h降水）
#   [2] 全国ランキング（気温高低・1h/3h/24h降水・最大風速・最小湿度・積雪深）
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
# JMA AMeDAS 公開API（認証不要）
# =============================================================================
LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.json"
AMEDAS_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
MAP_BASE_URL = "https://www.jma.go.jp/bosai/amedas/data/map"

DISCORD_AMEDAS_WEBHOOK_URL = os.environ.get("DISCORD_AMEDAS_WEBHOOK_URL", "")

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX  = os.environ.get("R2_PREFIX", "amedas").strip().strip("/")

# 秋田中心の JMA AMeDAS マップ参照リンク（Discord に添付）
JMA_AMEDAS_URL = (
    "https://www.jma.go.jp/bosai/map.html"
    "#9/39.615/140.218333333333/&elem=temp&contents=amedas&interval=60"
)

# JMA AMeDAS コードプレフィックス 32 = 秋田県
AKITA_CODE_PREFIX = "32"

RANK_TOP_N = int(os.environ.get("AMEDAS_RANK_TOP_N", "10"))

JST = timezone(timedelta(hours=9))

WIND_DIR_JP = ["北北東","北東","東北東","東","東南東","南東","南南東","南",
               "南南西","南西","西南西","西","西北西","北西","北北西","北"]

# 時系列詳細を出力する3地点
DETAIL_STATIONS = [
    ("32126", "鷹巣"),
    ("32402", "秋田"),
    ("32596", "横手"),
]

# =============================================================================
# 画像スタイル
# =============================================================================
C_TITLE_BG   = (45,  90, 145)
C_TITLE_FG   = (255, 255, 255)
C_HEADER_BG  = (85, 140, 200)
C_HEADER_FG  = (255, 255, 255)
C_ROW_ODD    = (255, 255, 255)
C_ROW_EVEN   = (238, 246, 255)
C_BORDER     = (190, 205, 220)
C_TEXT       = (30,  30,  30)
C_SECTION_BG = (60, 110, 170)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # ubuntu apt
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",           # macOS
    "/Library/Fonts/Arial Unicode.ttf",
]

# =============================================================================
# HTTP
# =============================================================================

def _fetch(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[WARN] HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"[WARN] fetch: {e} ({url})")
        return None


def _val(entry: dict, key: str) -> Optional[float]:
    v = entry.get(key)
    if isinstance(v, list) and len(v) >= 2 and v[1] in (0, 1):
        try:
            return float(v[0]) if v[0] is not None else None
        except (TypeError, ValueError):
            pass
    return None


# =============================================================================
# タイムスタンプ
# =============================================================================

def _parse_latest() -> Tuple[datetime, datetime]:
    raw = _fetch(LATEST_TIME_URL)
    if raw:
        utc = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    else:
        utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        utc = utc.replace(minute=(utc.minute // 10) * 10) - timedelta(minutes=10)
    return utc.astimezone(JST), utc


def _hourly_ts_list(base_utc: datetime, hours: int) -> List[str]:
    cur = base_utc.replace(minute=0, second=0, microsecond=0)
    result = []
    for _ in range(hours):
        result.append(cur.strftime("%Y%m%d%H%M%S"))
        cur -= timedelta(hours=1)
    return result


# =============================================================================
# 地点テーブル
# =============================================================================

def _load_akita_stations(table: dict) -> Dict[str, str]:
    result = {}
    for code, info in table.items():
        if not code.startswith(AKITA_CODE_PREFIX):
            continue
        elems = info.get("elems", "")
        if not elems or elems[0] != "1":
            continue
        result[code] = info.get("kjName", code)
    print(f"[INFO] 秋田県局（気温あり）: {len(result)} stations")
    return dict(sorted(result.items()))


# =============================================================================
# マップ一括取得
# =============================================================================

def _fetch_maps(ts_list: List[str]) -> Dict[str, dict]:
    maps: Dict[str, dict] = {}
    for ts in ts_list:
        data = _fetch(f"{MAP_BASE_URL}/{ts}.json")
        if data:
            maps[ts] = data
    print(f"[INFO] maps fetched: {len(maps)}/{len(ts_list)}")
    return maps


# =============================================================================
# データ集計（秋田県）
# =============================================================================

def _collect(
    akita: Dict[str, str],
    maps: Dict[str, dict],
    ts_list: List[str],
    jst_today_start_utc: datetime,
) -> List[dict]:
    results = []
    for code, name in akita.items():
        latest_entry = maps.get(ts_list[0], {}).get(code, {}) if ts_list else {}

        temp     = _val(latest_entry, "temp")
        wind     = _val(latest_entry, "wind")
        snow     = _val(latest_entry, "snow")
        wind_dir = _val(latest_entry, "windDirection")
        humidity = _val(latest_entry, "humidity")

        daily_temps: List[float] = []
        rn_by_ts: List[Tuple[datetime, float]] = []

        for ts_str in ts_list:
            ts_utc = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            entry = maps.get(ts_str, {}).get(code, {})
            t_val  = _val(entry, "temp")
            rn_val = _val(entry, "rn")
            if t_val is not None and ts_utc >= jst_today_start_utc:
                daily_temps.append(t_val)
            if rn_val is not None:
                rn_by_ts.append((ts_utc, rn_val))

        max_temp = max(daily_temps) if daily_temps else None
        min_temp = min(daily_temps) if daily_temps else None

        rn_sorted = sorted(rn_by_ts, key=lambda x: x[0], reverse=True)
        rn1h  = rn_sorted[0][1] if rn_sorted else 0.0
        rn3h  = sum(v for _, v in rn_sorted[:3])
        rn24h = sum(v for _, v in rn_sorted[:24])

        wd_jp = WIND_DIR_JP[int(wind_dir) - 1] if wind_dir and 1 <= wind_dir <= 16 else ""

        results.append({
            "name":     name,
            "temp":     temp,
            "max_temp": max_temp,
            "min_temp": min_temp,
            "humidity": humidity,
            "wind":     wind,
            "wind_dir": wd_jp,
            "snow":     snow,
            "rn1h":     rn1h,
            "rn3h":     rn3h,
            "rn24h":    rn24h,
        })
    return results


# =============================================================================
# 全国ランキング
# =============================================================================

def _ranking(maps: Dict[str, dict], ts_list: List[str], table: dict):
    latest_map = maps.get(ts_list[0], {}) if ts_list else {}

    def name_of(code):
        v = table.get(code)
        return v.get("kjName", code) if isinstance(v, dict) else code

    temps, winds, snows, hums = [], [], [], []
    for code, obs in latest_map.items():
        nm = name_of(code)
        t = _val(obs, "temp")
        w = _val(obs, "wind")
        s = _val(obs, "snow")
        h = _val(obs, "humidity")
        if t is not None: temps.append((nm, t))
        if w is not None: winds.append((nm, w))
        if s is not None and s > 0: snows.append((nm, s))
        if h is not None: hums.append((nm, h))

    # 積算降水（maps 共用）
    rn_totals: Dict[str, List[float]] = {}
    for ts_str in ts_list[:24]:
        for code, obs in maps.get(ts_str, {}).items():
            v = _val(obs, "rn")
            if v is not None:
                rn_totals.setdefault(code, []).append(v)

    rn1h_rank, rn3h_rank, rn24h_rank = [], [], []
    for code, vals in rn_totals.items():
        if not isinstance(table.get(code), dict):
            continue
        nm = name_of(code)
        v1  = vals[0] if vals else 0.0
        v3  = sum(vals[:3])
        v24 = sum(vals[:24])
        if v1  > 0: rn1h_rank.append((nm, v1))
        if v3  > 0: rn3h_rank.append((nm, v3))
        if v24 > 0: rn24h_rank.append((nm, v24))

    def top(lst, n=RANK_TOP_N, reverse=True):
        return sorted(lst, key=lambda x: x[1], reverse=reverse)[:n]

    return {
        "hot":    top(temps),
        "cold":   top(temps, reverse=False),
        "rn1h":   top(rn1h_rank),
        "rn3h":   top(rn3h_rank),
        "rn24h":  top(rn24h_rank),
        "wind":   top(winds),
        "dry":    top(hums, reverse=False),
        "snow":   top(snows),
    }


# =============================================================================
# 画像レンダリング
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


def _cell_w(draw, texts: List[str], font, pad: int = 16) -> int:
    """列内の最大テキスト幅からセル幅を決める。"""
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
    """テーブル画像を PNG バイト列で返す。"""
    from PIL import Image, ImageDraw

    right_align_cols = right_align_cols or set()

    # 仮描画でフォントを取得
    tmp = Image.new("RGB", (1, 1))
    tmp_d = ImageDraw.Draw(tmp)
    f_sm, f_md, f_lg = _load_fonts()
    if f_sm is None:
        raise ImportError("Pillow not available")

    ROW_H = 26
    HDR_H = 28
    TTL_H = 32
    PAD_X = 10

    # 列幅を計算（ヘッダー + 全データ）
    col_contents = [
        [h] + [r[i] for r in rows if i < len(r)]
        for i, h in enumerate(headers)
    ]
    col_widths = [_cell_w(tmp_d, col, f_sm) for col in col_contents]
    total_w = sum(col_widths) + len(col_widths) + 1
    total_h = TTL_H + HDR_H + len(rows) * ROW_H + 1

    img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # タイトル行
    d.rectangle([(0, 0), (total_w, TTL_H)], fill=C_TITLE_BG)
    d.text((PAD_X, (TTL_H - 15) // 2), title, fill=C_TITLE_FG, font=f_lg)

    # ヘッダー行
    y = TTL_H
    d.rectangle([(0, y), (total_w, y + HDR_H)], fill=C_HEADER_BG)
    x = 0
    for i, (hdr, cw) in enumerate(zip(headers, col_widths)):
        bb = d.textbbox((0, 0), hdr, font=f_sm)
        tw = bb[2] - bb[0]
        tx = x + (cw - tw) // 2
        d.text((tx, y + (HDR_H - 13) // 2), hdr, fill=C_HEADER_FG, font=f_sm)
        x += cw + 1

    y += HDR_H

    # データ行
    for ri, row in enumerate(rows):
        bg = C_ROW_ODD if ri % 2 == 0 else C_ROW_EVEN
        d.rectangle([(0, y), (total_w, y + ROW_H)], fill=bg)
        d.line([(0, y), (total_w, y)], fill=C_BORDER)
        x = 0
        for ci, (cell, cw) in enumerate(zip(row, col_widths)):
            bb = d.textbbox((0, 0), cell, font=f_sm)
            tw = bb[2] - bb[0]
            if ci in right_align_cols:
                tx = x + cw - tw - 6
            else:
                tx = x + 6
            d.text((tx, y + (ROW_H - 13) // 2), cell, fill=C_TEXT, font=f_sm)
            x += cw + 1
        y += ROW_H

    # 縦区切り線
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


def _draw_ranking_img(rankings: dict, jst_now: datetime) -> bytes:
    """全国ランキング複数セクションを縦並びで1枚の画像にする。"""
    from PIL import Image, ImageDraw

    f_sm, f_md, f_lg = _load_fonts()
    if f_sm is None:
        raise ImportError("Pillow not available")

    sections = [
        ("最高気温",    rankings["hot"],   "℃"),
        ("最低気温",    rankings["cold"],  "℃"),
        ("1h降水量",   rankings["rn1h"],  "mm"),
        ("3h降水量",   rankings["rn3h"],  "mm"),
        ("24h降水量",  rankings["rn24h"], "mm"),
        ("最大風速",   rankings["wind"],  "m/s"),
        ("最小湿度",   rankings["dry"],   "%"),
        ("積雪深",     rankings["snow"],  "cm"),
    ]

    # 実データがあるセクションだけ残す
    sections = [(ttl, items, unit) for ttl, items, unit in sections if items]

    if not sections:
        sections = [("（データなし）", [], "")]

    # 2列レイアウト
    tmp = Image.new("RGB", (1, 1))
    tmp_d = ImageDraw.Draw(tmp)

    RANK_H   = 22
    SEC_HDR  = 28
    SEC_PAD  = 8
    COL_PAD  = 10
    TTL_H    = 34

    # 列幅を一括計算（全セクション共通）
    all_names = [nm for _, items, _ in sections for nm, _ in items]
    all_vals  = [f"{v:.1f}{u}" for _, items, unit in sections for _, v in items
                 for u in [unit]]

    name_w = _cell_w(tmp_d, ["地点名"] + all_names, f_sm)
    val_w  = _cell_w(tmp_d, ["データ"] + all_vals,  f_sm)
    rank_w = _cell_w(tmp_d, ["順位", "10"], f_sm)
    sec_w  = rank_w + name_w + val_w + 4  # +2 borders

    # ペアで並べる
    pairs = [(sections[i], sections[i+1] if i+1 < len(sections) else None)
             for i in range(0, len(sections), 2)]

    def pair_h(left, right):
        n = max(len(left[1]), len(right[1]) if right else 0)
        return TTL_H + SEC_HDR + n * RANK_H + SEC_PAD * 2

    total_w = sec_w * 2 + COL_PAD * 3
    total_h = TTL_H + sum(pair_h(*p) + SEC_PAD for p in pairs)

    img = Image.new("RGB", (total_w, total_h), (245, 248, 252))
    d   = ImageDraw.Draw(img)

    # 全体タイトル
    ts = jst_now.strftime("%Y/%m/%d %H:%M JST")
    d.rectangle([(0, 0), (total_w, TTL_H)], fill=C_TITLE_BG)
    d.text((COL_PAD, (TTL_H - 15) // 2), f"全国ランキング　{ts}", fill=C_TITLE_FG, font=f_lg)

    def draw_section(title, items, unit, ox, oy, width):
        # セクション見出し
        d.rectangle([(ox, oy), (ox + width, oy + SEC_HDR)], fill=C_SECTION_BG)
        bb = d.textbbox((0, 0), title, font=f_md)
        d.text((ox + 8, oy + (SEC_HDR - (bb[3]-bb[1])) // 2), title, fill=C_TITLE_FG, font=f_md)
        # 列ヘッダー
        y = oy + SEC_HDR
        d.rectangle([(ox, y), (ox + width, y + RANK_H)], fill=C_HEADER_BG)
        for ci, (label, cw) in enumerate(zip(["順位", "地点名", "データ"],
                                              [rank_w, name_w, val_w])):
            bb = d.textbbox((0, 0), label, font=f_sm)
            tx = ox + sum([rank_w, name_w, val_w][:ci]) + ci + (cw - (bb[2]-bb[0])) // 2
            d.text((tx, y + (RANK_H - 13) // 2), label, fill=C_HEADER_FG, font=f_sm)
        y += RANK_H
        # データ行
        for ri, (nm, v) in enumerate(items):
            bg = C_ROW_ODD if ri % 2 == 0 else C_ROW_EVEN
            d.rectangle([(ox, y), (ox + width, y + RANK_H)], fill=bg)
            d.line([(ox, y), (ox + width, y)], fill=C_BORDER)
            rank_str = str(ri + 1)
            val_str  = f"{v:.1f}{unit}"
            # 順位（右寄せ）
            bb = d.textbbox((0, 0), rank_str, font=f_sm)
            d.text((ox + rank_w - (bb[2]-bb[0]) - 6, y + (RANK_H - 13) // 2),
                   rank_str, fill=C_TEXT, font=f_sm)
            # 地点名（左寄せ）
            d.text((ox + rank_w + 1 + 6, y + (RANK_H - 13) // 2),
                   nm, fill=C_TEXT, font=f_sm)
            # 値（右寄せ）
            bb = d.textbbox((0, 0), val_str, font=f_sm)
            d.text((ox + rank_w + 1 + name_w + 1 + val_w - (bb[2]-bb[0]) - 6,
                    y + (RANK_H - 13) // 2),
                   val_str, fill=C_TEXT, font=f_sm)
            y += RANK_H
        # ボーダー
        d.rectangle([(ox, oy), (ox + width - 1, y)], outline=C_BORDER)
        return y + SEC_PAD

    y = TTL_H + SEC_PAD
    for left, right in pairs:
        ox_l = COL_PAD
        ox_r = COL_PAD + sec_w + COL_PAD
        n = max(len(left[1]), len(right[1]) if right else 0)
        sec_h = SEC_HDR + RANK_H + n * RANK_H + SEC_PAD

        draw_section(left[0], left[1], left[2], ox_l, y, sec_w)
        if right:
            draw_section(right[0], right[1], right[2], ox_r, y, sec_w)
        y += sec_h + SEC_PAD

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fmt_akita_rows(results: List[dict]) -> Tuple[List[str], List[List[str]]]:
    # "日最高/日最低" = 当日0:00〜現在の最高/最低（現在気温は削除）
    headers = ["地点名", "日最高℃", "日最低℃", "湿度%", "風速m/s", "風向", "前1h雨mm", "日積算雨mm"]
    rows = []
    for r in results:
        def tf(v): return f"{v:.1f}" if v is not None else "---"
        def rf(v): return f"{v:.1f}" if v > 0 else "0.0"
        hum = f"{r['humidity']:.0f}" if r["humidity"] is not None else "---"
        wsp = f"{r['wind']:.1f}" if r["wind"] is not None else "---"
        rows.append([
            r["name"],
            tf(r["max_temp"]),
            tf(r["min_temp"]),
            hum,
            wsp,
            r["wind_dir"] or "---",
            rf(r["rn1h"]),
            rf(r["rn24h"]),
        ])
    return headers, rows


def _station_detail_rows(
    maps: Dict[str, dict],
    ts_list: List[str],
    code: str,
    jst_today_start_utc: datetime,
) -> List[List[str]]:
    """1局の時系列データ行（新しい順）を返す。"""
    daily_rn = 0.0
    raw = []
    for ts_str in reversed(ts_list):   # oldest → newest で日積算を積む
        ts_utc = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        ts_jst = ts_utc.astimezone(JST)
        entry  = maps.get(ts_str, {}).get(code, {})

        temp     = _val(entry, "temp")
        rn       = _val(entry, "rn")
        wind     = _val(entry, "wind")
        wd_code  = _val(entry, "windDirection")
        sun1h    = _val(entry, "sun1h")
        humidity = _val(entry, "humidity")

        if ts_utc >= jst_today_start_utc and rn is not None:
            daily_rn += rn

        wd_jp = WIND_DIR_JP[int(wd_code) - 1] if wd_code and 1 <= wd_code <= 16 else "---"

        def tf(v): return f"{v:.1f}" if v is not None else "---"

        raw.append([
            f"{ts_jst.day}日 {ts_jst.strftime('%H:%M')}",
            tf(temp),
            f"{rn:.1f}" if rn is not None else "0.0",
            f"{daily_rn:.1f}",
            wd_jp,
            tf(wind),
            f"{sun1h:.1f}" if sun1h is not None else "---",
            f"{humidity:.0f}" if humidity is not None else "---",
        ])

    return list(reversed(raw))   # newest first


def _draw_3station_detail_img(
    maps: Dict[str, dict],
    ts_list: List[str],
    jst_today_start_utc: datetime,
    jst_now: datetime,
) -> bytes:
    """3地点の時系列詳細テーブルを縦積みした1枚のPNGを返す。"""
    from PIL import Image

    ts_str  = jst_now.strftime("%Y/%m/%d %H:%M JST")
    headers = ["日時", "気温℃", "前1h降水mm", "日積算降水mm", "風向", "風速m/s", "日照h", "湿度%"]
    right_c = {1, 2, 3, 5, 6, 7}

    png_list = []
    for code, name in DETAIL_STATIONS:
        rows = _station_detail_rows(maps, ts_list, code, jst_today_start_utc)
        png  = _draw_table_img(
            title=f"アメダス {name}（{code}）  {ts_str}",
            headers=headers,
            rows=rows,
            right_align_cols=right_c,
        )
        png_list.append(png)

    # 縦に連結
    imgs  = [Image.open(io.BytesIO(p)) for p in png_list]
    gap   = 6
    w     = max(img.width for img in imgs)
    h     = sum(img.height for img in imgs) + gap * (len(imgs) - 1)
    combo = Image.new("RGB", (w, h), (235, 240, 248))
    y_off = 0
    for img in imgs:
        combo.paste(img, (0, y_off))
        y_off += img.height + gap

    buf = io.BytesIO()
    combo.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# =============================================================================
# R2 アップロード
# =============================================================================

def _upload_r2(items: List[Tuple[str, bytes]], jst_now: datetime) -> List[str]:
    """(filename, bytes) リストを R2 にアップして URL リストを返す。"""
    if not R2_ENABLE:
        return []
    try:
        from module.utils.r2_utils import put_bytes, make_url
    except ImportError:
        print("[WARN] r2_utils not available")
        return []

    day  = jst_now.strftime("%Y%m%d")
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
    jst_now: datetime,
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
    page_id = create_db_row(
        title=title,
        category="Amedas",
        init_jst_iso=jst_now.isoformat(),
        memo="",
        rjtd="",
        prefix=R2_PREFIX,
        r2_url=next((u for u in r2_urls if u), ""),
        autogen=True,
        icon_emoji="🌡️",
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
        append_bookmark(page_id, JMA_AMEDAS_URL,
                        caption="気象庁 アメダス（秋田）")
    except Exception as e:
        print(f"[WARN] Notion bookmarks failed: {e}")

    print(f"[OK] Notion page: {page_id}")


# =============================================================================
# Discord 送信
# =============================================================================

def _post_image(image_bytes: bytes, filename: str, content: str = ""):
    """Discord Webhook にファイルを添付して送信する。"""
    if not DISCORD_AMEDAS_WEBHOOK_URL:
        print(f"[SKIP] DISCORD_AMEDAS_WEBHOOK_URL not set")
        return

    boundary = "----AmedasBotBoundary7fK2"
    crlf = b"\r\n"

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
        DISCORD_AMEDAS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)",
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
    print("=== Start Amedas ===")

    jst_now, latest_utc = _parse_latest()
    print(f"[INFO] latest obs: {jst_now.strftime('%Y-%m-%d %H:%M JST')}")

    table = _fetch(AMEDAS_TABLE_URL) or {}
    akita = _load_akita_stations(table)
    ts_list = _hourly_ts_list(latest_utc, 24)
    jst_today_start_utc = jst_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    maps = _fetch_maps(ts_list)

    results  = _collect(akita, maps, ts_list, jst_today_start_utc)
    rankings = _ranking(maps, ts_list, table)

    ts_hourly_jst = (
        datetime.strptime(ts_list[0], "%Y%m%d%H%M%S")
        .replace(tzinfo=timezone.utc)
        .astimezone(JST)
    )
    ts_hourly_str = ts_hourly_jst.strftime("%Y/%m/%d %H:%M JST")

    detail_headers = ["日時", "気温℃", "前1h降水mm", "日積算降水mm", "風向", "風速m/s", "日照h", "湿度%"]
    detail_right   = {1, 2, 3, 5, 6, 7}

    # 秋田県一覧
    headers, rows = _fmt_akita_rows(results)
    img1 = _draw_table_img(
        title=f"アメダス 秋田県  {ts_hourly_str}  （日最高/日最低は0:00〜現在）",
        headers=headers,
        rows=rows,
        right_align_cols={1, 2, 3, 4, 6, 7},
    )
    print(f"[INFO] akita image: {len(img1)} bytes")

    # 全国ランキング
    img2 = _draw_ranking_img(rankings, ts_hourly_jst)
    print(f"[INFO] ranking image: {len(img2)} bytes")

    # 3地点 時系列詳細
    detail_imgs: List[Tuple[str, bytes]] = []
    for code, name in DETAIL_STATIONS:
        rows_d = _station_detail_rows(maps, ts_list, code, jst_today_start_utc)
        img_d  = _draw_table_img(
            title=f"アメダス {name}（{code}）  {ts_hourly_str}",
            headers=detail_headers,
            rows=rows_d,
            right_align_cols=detail_right,
        )
        print(f"[INFO] detail {name}: {len(img_d)} bytes")
        detail_imgs.append((f"amedas_detail_{name}.png", img_d))

    # R2 アップロード
    img_items: List[Tuple[str, bytes]] = [
        ("amedas_akita.png",    img1),
        ("amedas_ranking.png",  img2),
    ] + detail_imgs
    r2_urls = _upload_r2(img_items, jst_now)

    # Notion 書き込み
    _notion_write(
        f"AMeDAS 秋田 / {ts_hourly_str}",
        r2_urls,
        jst_now,
    )

    # Discord 投稿（順序は変わらず）
    _post_image(img1, "amedas_akita.png", content=f"<{JMA_AMEDAS_URL}>")
    _post_image(img2, "amedas_ranking.png")
    for fname, img_d in detail_imgs:
        _post_image(img_d, fname)

    print("=== Done ===")


# =============================================================================
# WCN アメダス観測値・ランキング スクリーンショット
# =============================================================================
WCN_USER      = os.environ.get("WEATHERCASTER_USER", "").strip()
WCN_PASS      = os.environ.get("WEATHERCASTER_PASS", "").strip()
WCN_WAIT_MS   = int(os.environ.get("GUIDANCE_WAIT_MS", "3000"))
WCN_VP_W      = int(os.environ.get("GUIDANCE_VIEWPORT_WIDTH",  "1400"))
WCN_VP_H      = int(os.environ.get("GUIDANCE_VIEWPORT_HEIGHT", "1200"))
WCN_ALLAMEDAS_URL = os.environ.get(
    "WCN_ALLAMEDAS_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/amedas/allamedas.html",
)
WCN_RANKING_URL = os.environ.get(
    "WCN_RANKING_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/amedas/ranking.html",
)


def _wcn_label_banner(raw: bytes, label: str) -> bytes:
    """スクリーンショットの上部にラベルバナーを追加。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        banner_h = 36
        banner = Image.new("RGB", (img.width, banner_h), (30, 30, 60))
        draw = ImageDraw.Draw(banner)
        try:
            font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 20)
        except Exception:
            font = ImageFont.load_default()
        draw.text((8, 6), label, fill=(255, 255, 255), font=font)
        combined = Image.new("RGB", (img.width, banner_h + img.height))
        combined.paste(banner, (0, 0))
        combined.paste(img, (0, banner_h))
        buf = io.BytesIO()
        combined.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return raw


def screenshot_wcn_amedas_pages() -> List[Tuple[str, bytes]]:
    """WCN アメダス地点一覧とランキングをスクリーンショット。

    allamedas.html: 3時間降水量/最高気温/最低気温/最大風速/最小湿度/積雪深（最大6枚）
    ranking.html  : 気温ランキング / 降水量ランキング / 風速・湿度・積雪ランキング（3枚）
    """
    if not (WCN_USER and WCN_PASS):
        print("[SKIP] WEATHERCASTER_USER/PASS 未設定 — WCN アメダス スクリーンショットをスキップ")
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[WARN] playwright 未インストール — WCN アメダス スクリーンショットをスキップ")
        return []

    results: List[Tuple[str, bytes]] = []

    def _wait(page):
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(WCN_WAIT_MS)

    ALLAMEDAS_ANCHOR = os.environ.get("WCN_ALLAMEDAS_ANCHOR", "15")  # 秋田のアンカーID

    def _shot_pref_section(page) -> bytes:
        """data_area を秋田アンカーへスクロールしてビューポート撮影。"""
        df = page.frame(name="data_area")
        if not df:
            raise RuntimeError("data_area not found")
        # アンカー (#15) にスクロール
        try:
            df.evaluate(f"document.getElementById('{ALLAMEDAS_ANCHOR}')?.scrollIntoView()")
            df.evaluate("window.scrollBy(0, -40)")  # ヘッダー行を含めて少し上へ
            page.wait_for_timeout(300)
        except Exception:
            pass
        # iframe をビューポート高に固定して撮影（縦長にしない）
        page.evaluate(
            f"document.querySelector('iframe[name=\"data_area\"]').style.height = '{WCN_VP_H}px'"
        )
        page.wait_for_timeout(200)
        return page.locator('iframe[name="data_area"]').screenshot()

    def _shot_full(page) -> bytes:
        """data_area を全高展開して撮影（ランキング用）。"""
        df = page.frame(name="data_area")
        if not df:
            raise RuntimeError("data_area not found")
        scroll_h = df.evaluate("document.body.scrollHeight")
        page.evaluate(
            f"document.querySelector('iframe[name=\"data_area\"]').style.height = '{scroll_h}px'"
        )
        page.wait_for_timeout(300)
        return page.locator('iframe[name="data_area"]').screenshot()

    def _submit_form(page, select_name: str, value: str):
        ff = page.frame(name="form_area")
        if not ff:
            raise RuntimeError("form_area not found")
        ff.select_option(f'select[name="{select_name}"]', value=value)
        page.wait_for_timeout(200)
        ff.locator('input[type="submit"], button[type="submit"]').first.click()
        _wait(page)

    def _select_by_idx(page, idx: int):
        ff = page.frame(name="form_area")
        if not ff:
            raise RuntimeError("form_area not found")
        sel = ff.locator("select").first
        options = sel.locator("option").all()
        if idx >= len(options):
            raise IndexError(f"option index {idx} >= {len(options)}")
        val = options[idx].get_attribute("value")
        sel.select_option(value=val)
        page.wait_for_timeout(200)
        ff.locator('input[type="submit"], button[type="submit"]').first.click()
        _wait(page)

    def _debug_form_opts(page) -> List[str]:
        ff = page.frame(name="form_area")
        if not ff:
            return []
        try:
            return ff.locator("select").first.locator("option").all_text_contents()
        except Exception:
            return []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            http_credentials={"username": WCN_USER, "password": WCN_PASS},
            viewport={"width": WCN_VP_W, "height": WCN_VP_H},
        )
        page = ctx.new_page()

        # ---- 1. allamedas.html ----------------------------------------
        ALLAMEDAS_ITEMS = [
            ("element", "rain3h", "wcn_amedas_rain3h.png", "アメダス 3時間降水量"),
            ("element", "tmax",   "wcn_amedas_tmax.png",   "アメダス 最高気温"),
            ("element", "tmin",   "wcn_amedas_tmin.png",   "アメダス 最低気温"),
            ("element", "wmax",   "wcn_amedas_wmax.png",   "アメダス 最大風速"),
            ("element", "humin",  "wcn_amedas_humin.png",  "アメダス 最小湿度"),
            ("element", "snow",   "wcn_amedas_snow.png",   "アメダス 積雪深"),
        ]
        for select_name, value, fname, lbl in ALLAMEDAS_ITEMS:
            try:
                page.goto(WCN_ALLAMEDAS_URL, wait_until="networkidle", timeout=60_000)
                _wait(page)
                opts = _debug_form_opts(page)
                print(f"[DEBUG] allamedas opts: {opts}")
                try:
                    _submit_form(page, select_name, value)
                except Exception:
                    ff = page.frame(name="form_area")
                    if ff:
                        sel = ff.locator("select").first
                        try:
                            sel.select_option(value=value)
                        except Exception:
                            for opt in sel.locator("option").all():
                                if value in opt.inner_text() or lbl.split()[-1] in opt.inner_text():
                                    sel.select_option(value=opt.get_attribute("value"))
                                    break
                        try:
                            ff.locator('input[type="submit"], button[type="submit"]').first.click()
                            _wait(page)
                        except Exception:
                            pass
                raw = _shot_pref_section(page)
                img = _wcn_label_banner(raw, lbl)
                results.append((fname, img))
                print(f"[OK] {fname}  {len(img):,} bytes")
            except Exception as e:
                print(f"[WARN] {fname} 撮影失敗: {e}")

        # ---- 2. ranking.html ------------------------------------------
        RANKING_GROUPS = [
            ("wcn_ranking_temp.png",  "ランキング 気温（最高↑ / 最低↓ / 低最高↓ / 高最低↑）"),
            ("wcn_ranking_rain.png",  "ランキング 降水量（1h / 3h / 12h / 24h）"),
            ("wcn_ranking_wind.png",  "ランキング 風速・湿度・積雪（最大風速 / 最大瞬間 / 最小湿度 / 積雪深）"),
        ]
        try:
            page.goto(WCN_RANKING_URL, wait_until="networkidle", timeout=60_000)
            _wait(page)
            rank_opts = _debug_form_opts(page)
            print(f"[DEBUG] ranking opts: {rank_opts}")
        except Exception as e:
            print(f"[WARN] ranking.html ロード失敗: {e}")
            rank_opts = []

        for idx, (fname, lbl) in enumerate(RANKING_GROUPS):
            try:
                page.goto(WCN_RANKING_URL, wait_until="networkidle", timeout=60_000)
                _wait(page)
                if len(rank_opts) >= 3:
                    _select_by_idx(page, idx)
                else:
                    print(f"[INFO] ranking opts < 3 — 全体撮影: {fname}")
                raw = _shot_full(page)
                img = _wcn_label_banner(raw, lbl)
                results.append((fname, img))
                print(f"[OK] {fname}  {len(img):,} bytes")
            except Exception as e:
                print(f"[WARN] {fname} 撮影失敗: {e}")

        browser.close()

    return results


def post_wcn_amedas_to_discord(images: List[Tuple[str, bytes]]) -> None:
    """WCN アメダス画像を Discord #amedas チャンネルへ投稿。"""
    url = DISCORD_AMEDAS_WEBHOOK_URL
    if not url:
        print("[SKIP] DISCORD_AMEDAS_WEBHOOK_URL 未設定 — Discord 投稿をスキップ")
        return

    import json as _json
    import uuid

    allamedas = [(f, b) for f, b in images if f.startswith("wcn_amedas_")]
    rankings  = [(f, b) for f, b in images if f.startswith("wcn_ranking_")]

    def _post_multipart(files: List[Tuple[str, bytes]], content: str = "") -> None:
        if not files:
            return
        boundary = uuid.uuid4().hex
        body = b""
        if content:
            body += (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="payload_json"\r\n\r\n'
                f'{_json.dumps({"content": content, "flags": 4})}\r\n'
            ).encode()
        for i, (fname, data) in enumerate(files):
            body += (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="files[{i}]"; '
                f'filename="{fname}"\r\n'
                f'Content-Type: image/png\r\n\r\n'
            ).encode() + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "discord-bot/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"[Discord] POST {resp.status} ({content or 'no content'})")
        except Exception as e:
            print(f"[WARN] Discord POST 失敗: {e}")

    if allamedas:
        _post_multipart(allamedas, content="**アメダス観測値（WCN）**")
    for i, item in enumerate(rankings):
        _post_multipart([item], content="**アメダスランキング（WCN）**" if i == 0 else "")


def main_wcn() -> None:
    """WCN アメダス観測値・ランキング: スクリーンショット → R2 → Discord → Notion。"""
    jst_now = datetime.now(JST)
    images = screenshot_wcn_amedas_pages()
    if not images:
        print("[INFO] WCN アメダス画像なし — スキップ")
        return

    r2_urls = _upload_r2(images, jst_now)
    post_wcn_amedas_to_discord(images)

    ts = jst_now.strftime("%m/%d %H:%M")
    _notion_write(
        title=f"WCN アメダス観測値・ランキング / {ts}",
        r2_urls=r2_urls,
        jst_now=jst_now,
    )


if __name__ == "__main__":
    main()
