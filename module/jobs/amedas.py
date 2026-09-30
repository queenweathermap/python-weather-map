# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# JMA AMeDAS データ → Discord 画像配信
#
# main()     : JMA公開API(urllib + Pillow, 認証不要)から鷹巣・秋田・横手
#              3地点の時系列詳細テーブルPNGを作る。discord_webhook_url引数で
#              投稿先を差し替えられる。2026-09-18より呼び出し元は
#              module/jobs/weather_warning.pyのみ(jma-warningチャンネル
#              向けに1日3回)。post_discord/post_notionともFalseで呼び出され、
#              Discord投稿・Notion記録は呼び出し元(weather_warning.py)が
#              警報スクショと合わせて1件にまとめて行う。
# main_ranking() : 秋田県観測値一覧＋全国ランキング。177chart.comの表示を撮影して配信
#              （撮れなかった画像はJMA公開APIからPillowで描画して補う。collect_images参照）
#              （2026-09-30、WCNサーバ停止によりスクショ方式から置換）。
# 配信: scripts/jma_amedas.py経由で朝6時/12時/18時（JST）にmain_ranking()のみ実行し、
#      R2保存・Discord(#amedas)投稿・Notion記録まで行う。
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
LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
MAP_BASE_URL = "https://www.jma.go.jp/bosai/amedas/data/map"

DISCORD_AMEDAS_WEBHOOK_URL = os.environ.get("DISCORD_AMEDAS_WEBHOOK_URL", "")

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX  = os.environ.get("R2_PREFIX", "amedas").strip().strip("/")

# 秋田中心の JMA AMeDAS マップ参照リンク（Discord に添付）
JMA_AMEDAS_URL = (
    "https://www.jma.go.jp/bosai/map.html"
    "#9/39.615/140.218333333333/&elem=temp&contents=amedas&interval=60"
)

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
    utc = _fetch_latest_utc()
    return utc.astimezone(JST), utc


def _hourly_ts_list(base_utc: datetime, hours: int) -> List[str]:
    cur = base_utc.replace(minute=0, second=0, microsecond=0)
    result = []
    for _ in range(hours):
        result.append(cur.strftime("%Y%m%d%H%M%S"))
        cur -= timedelta(hours=1)
    return result


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
    cell_colors: Optional[Dict[Tuple[int, int], Tuple[int, int, int]]] = None,
) -> bytes:
    """テーブル画像を PNG バイト列で返す。cell_colors={(行, 列): RGB} でセルを塗れる。"""
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
            if cell_colors and (ri, ci) in cell_colors:
                d.rectangle([(x, y + 1), (x + cw - 1, y + ROW_H - 1)], fill=cell_colors[(ri, ci)])
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

    day_hm = jst_now.strftime("%Y%m%d/%H%M")
    urls: List[str] = []
    for fname, data in items:
        key = f"{R2_PREFIX}/{day_hm}/{fname}"
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

def _nearest_scheduled_slot_jst(now: datetime, hours: List[int]) -> datetime:
    """実行が数分〜数時間遅れても、YMLプロパティはyml上の狙い撃ちスケジュール
    時刻ぴったりの表示にする。"""
    best_h = min(hours, key=lambda h: min(abs(now.hour - h), 24 - abs(now.hour - h)))
    return now.replace(hour=best_h, minute=0, second=0, microsecond=0)


def _notion_write(
    title: str,
    r2_urls: List[str],
    jst_now: datetime,
    yml_jst: Optional[datetime] = None,
) -> None:
    try:
        from module.utils.notion_utils import archive_to_notion
    except ImportError:
        print("[WARN] notion_utils not available")
        return

    archive_to_notion(
        title=title,
        category="AMeDAS",
        r2_urls=r2_urls,
        jst_now=jst_now,
        pwa=False,
        icon_emoji="🌡️",
        # Discordの投稿と同じリンク文言に揃える(2026-09-17)。
        links=[("アメダス（秋田）", JMA_AMEDAS_URL), ("177chart アメダスランキング", f"{SITE_BASE}/amedas-ranking/")],
        yml_jst=yml_jst,
    )


# =============================================================================
# Discord 送信
# =============================================================================

def _post_image(image_bytes: bytes, filename: str, content: str = "", webhook_url: str = ""):
    """Discord Webhook にファイルを添付して送信する。webhook_url省略時は
    DISCORD_AMEDAS_WEBHOOK_URL(#amedas)を使う。jma-warningチャンネルなど
    別の投稿先に送りたい呼び出し元は明示的に渡す。"""
    webhook_url = webhook_url or DISCORD_AMEDAS_WEBHOOK_URL
    if not webhook_url:
        print(f"[SKIP] webhook url not set")
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
        webhook_url,
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

def main(
    post_discord: bool = True,
    post_notion: bool = True,
    discord_webhook_url: str = "",
) -> List[Tuple[str, bytes]]:
    print("=== Start Amedas ===")

    jst_now, latest_utc = _parse_latest()
    print(f"[INFO] latest obs: {jst_now.strftime('%Y-%m-%d %H:%M JST')}")

    ts_list = _hourly_ts_list(latest_utc, 24)
    jst_today_start_utc = jst_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    maps = _fetch_maps(ts_list)

    ts_hourly_jst = (
        datetime.strptime(ts_list[0], "%Y%m%d%H%M%S")
        .replace(tzinfo=timezone.utc)
        .astimezone(JST)
    )
    ts_hourly_str = ts_hourly_jst.strftime("%Y/%m/%d %H:%M JST")

    detail_headers = ["日時", "気温℃", "前1h降水mm", "日積算降水mm", "風向", "風速m/s", "日照h", "湿度%"]
    detail_right   = {1, 2, 3, 5, 6, 7}

    # 3地点 時系列詳細（鷹巣・秋田・横手）
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
    r2_urls = _upload_r2(detail_imgs, jst_now)

    # Notion 書き込み
    if post_notion:
        _notion_write(
            f"AMeDAS 秋田 / {ts_hourly_str}",
            r2_urls,
            jst_now,
        )

    # Discord 投稿（呼び出し元が制御する場合は skip。discord_webhook_url指定時は
    # #amedasの代わりにそちらへ投稿する）
    if post_discord:
        for i, (fname, img_d) in enumerate(detail_imgs):
            content = f"<{JMA_AMEDAS_URL}>" if i == 0 else ""
            _post_image(img_d, fname, content=content, webhook_url=discord_webhook_url)

    return detail_imgs, r2_urls


# =============================================================================
# アメダス観測値一覧（秋田）・全国ランキング（JMA公開API版）
#
# 旧WCN会員ページ(allamedas/ranking)のスクショ方式は、WCNサーバ停止により
# 取得できなくなったため、JMA公開API(map)の正時値から同等の表を自前で描画する。
# 日最高/最低・最大風速・最小湿度・12h雨量は「当日0時JST〜最新」の正時値からの
# 集計(10分値ではない)。最大瞬間風速はmapに含まれないためランキングから除外。
# =============================================================================

PREF_LABEL = {
    "11": "宗谷", "12": "上川", "13": "留萌", "14": "石狩", "15": "空知", "16": "後志",
    "17": "網走", "18": "根室", "19": "釧路", "20": "十勝", "21": "胆振", "22": "日高",
    "23": "渡島", "24": "檜山", "31": "青森", "32": "秋田", "33": "岩手", "34": "宮城",
    "35": "山形", "36": "福島", "40": "茨城", "41": "栃木", "42": "群馬", "43": "埼玉",
    "44": "東京", "45": "千葉", "46": "神奈川", "48": "長野", "49": "山梨", "50": "静岡",
    "51": "愛知", "52": "岐阜", "53": "三重", "54": "新潟", "55": "富山", "56": "石川",
    "57": "福井", "60": "滋賀", "61": "京都", "62": "大阪", "63": "兵庫", "64": "奈良",
    "65": "和歌山", "66": "岡山", "67": "広島", "68": "島根", "69": "鳥取", "71": "徳島",
    "72": "香川", "73": "愛媛", "74": "高知", "81": "山口", "82": "福岡", "83": "大分",
    "84": "長崎", "85": "佐賀", "86": "熊本", "87": "宮崎", "88": "鹿児島", "91": "沖縄",
    "92": "大東島", "93": "宮古島", "94": "八重山",
}
RANK_TOP_N = int(os.environ.get("AMEDAS_RANK_TOP_N", "10"))


def _fetch_latest_utc() -> datetime:
    """最新観測時刻(UTC)。latest_time.txt はJSONでなくISO文字列そのもの。"""
    try:
        req = urllib.request.Request(
            LATEST_TIME_URL, headers={"User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return datetime.fromisoformat(r.read().decode().strip()).astimezone(timezone.utc)
    except Exception as e:
        print(f"[WARN] latest_time: {e} — 現在時刻から推定")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        return now.replace(minute=(now.minute // 10) * 10) - timedelta(minutes=20)


def _collect_stats() -> Tuple[Dict[str, dict], Dict[str, dict], datetime]:
    """全アメダス局の集計値を返す: ({code: stat}, amedastable, 最新時刻JST)。"""
    table = _fetch("https://www.jma.go.jp/bosai/amedas/const/amedastable.json") or {}
    latest = _fetch_latest_utc()
    latest_jst = latest.astimezone(JST)
    day_start_utc = latest_jst.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    maps = _fetch_maps([latest.strftime("%Y%m%d%H%M%S")])            # 最新(10分値)
    ts_list = _hourly_ts_list(latest, 24)                              # 正時24本
    maps.update(_fetch_maps(ts_list))
    latest_map = maps.get(latest.strftime("%Y%m%d%H%M%S"), {})
    if not latest_map:
        return {}, table, latest_jst

    def ts_dt(ts: str) -> datetime:
        return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

    today_ts = [ts for ts in ts_list if ts in maps and ts_dt(ts) >= day_start_utc]
    last12 = [ts for ts in ts_list[:12] if ts in maps]

    stats: Dict[str, dict] = {}
    for code, e in latest_map.items():
        s = {
            "temp": _val(e, "temp"), "r1": _val(e, "precipitation1h"),
            "r3": _val(e, "precipitation3h"), "r24": _val(e, "precipitation24h"),
            "wind": _val(e, "wind"), "wdir": _val(e, "windDirection"),
            "hum": _val(e, "humidity"), "snow": _val(e, "snow"),
        }
        def series(key, tss):
            out = []
            for ts in tss:
                v = _val(maps[ts].get(code, {}), key)
                if v is not None:
                    out.append(v)
            return out
        temps = series("temp", today_ts) + ([s["temp"]] if s["temp"] is not None else [])
        winds = series("wind", today_ts) + ([s["wind"]] if s["wind"] is not None else [])
        hums = series("humidity", today_ts) + ([s["hum"]] if s["hum"] is not None else [])
        s["tmax"] = max(temps) if temps else None
        s["tmin"] = min(temps) if temps else None
        s["wmax"] = max(winds) if winds else None
        s["hmin"] = min(hums) if hums else None
        r12 = series("precipitation1h", last12)
        s["r12"] = sum(r12) if len(r12) >= 11 else None
        stats[code] = s
    return stats, table, latest_jst


def _fmt(v: Optional[float], nd: int = 1) -> str:
    return "---" if v is None else f"{v:.{nd}f}"


def _akita_table_image(stats: Dict[str, dict], table: Dict[str, dict], when: datetime) -> Optional[bytes]:
    codes = sorted(c for c in stats if c.startswith("32"))
    if not codes:
        return None
    has_snow = any(stats[c]["snow"] is not None for c in codes)
    headers = ["地点", "気温", "最高", "最低", "1h雨", "3h雨", "24h雨", "風向", "風速", "最大風速", "最小湿度"]
    if has_snow:
        headers.append("積雪深")
    rows = []
    for c in codes:
        s = stats[c]
        wd = s["wdir"]
        wd_jp = WIND_DIR_JP[int(wd) - 1] if wd and 1 <= wd <= 16 else "---"
        row = [table.get(c, {}).get("kjName", c), _fmt(s["temp"]), _fmt(s["tmax"]), _fmt(s["tmin"]),
               _fmt(s["r1"]), _fmt(s["r3"]), _fmt(s["r24"]), wd_jp, _fmt(s["wind"]),
               _fmt(s["wmax"]), _fmt(s["hmin"], 0)]
        if has_snow:
            row.append(_fmt(s["snow"], 0))
        rows.append(row)
    return _draw_table_img(
        f"アメダス観測値 秋田県  {when.strftime('%m/%d %H:%M')}現在（気温℃・雨mm・風m/s・湿度%）",
        headers, rows, right_align_cols=set(range(1, len(headers))) - {7},
    )


def _rank_table(stats, table, key, title, reverse, unit_nd=1, min_val=None) -> Optional[bytes]:
    items = [(c, s[key]) for c, s in stats.items() if s.get(key) is not None]
    if min_val is not None:
        items = [(c, v) for c, v in items if v >= min_val]
    if not items:
        return None
    items.sort(key=lambda x: x[1], reverse=reverse)
    rows = []
    for i, (c, v) in enumerate(items[:RANK_TOP_N], 1):
        nm = table.get(c, {}).get("kjName", c)
        rows.append([str(i), f"{nm}({PREF_LABEL.get(c[:2], '')})", _fmt(v, unit_nd)])
    return _draw_table_img(title, ["順位", "地点", "値"], rows, right_align_cols={0, 2})


def _compose_2x2(img_bytes_list: List[bytes], pad: int = 6) -> bytes:
    from PIL import Image as PILImage
    imgs = [PILImage.open(io.BytesIO(b)).convert("RGB") for b in img_bytes_list]
    nrows = (len(imgs) + 1) // 2
    col_w = max(i.width for i in imgs)
    row_h = max(i.height for i in imgs)
    canvas = PILImage.new("RGB", (col_w * 2 + pad, row_h * nrows + pad * (nrows - 1)), (220, 220, 220))
    for i, img in enumerate(imgs):
        r, c = divmod(i, 2)
        canvas.paste(img, (c * (col_w + pad), r * (row_h + pad)))
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()


def build_amedas_images() -> List[Tuple[str, bytes]]:
    """秋田県観測値一覧 + 全国ランキング3枚（気温/降水/風・湿度・積雪）を作る。"""
    stats, table, when = _collect_stats()
    if not stats:
        print("[WARN] アメダスmap取得失敗")
        return []
    images: List[Tuple[str, bytes]] = []
    img = _akita_table_image(stats, table, when)
    if img:
        images.append(("amedas_akita.png", img))

    def group(fname, specs):
        tabs = [t for t in (_rank_table(stats, table, *sp) for sp in specs) if t]
        if tabs:
            images.append((fname, _compose_2x2(tabs)))

    group("amedas_ranking_temp.png", [
        ("tmax", "最高気温 高い順(℃)", True),
        ("tmin", "最低気温 低い順(℃)", False),
        ("tmax", "最高気温 低い順(℃)", False),
        ("tmin", "最低気温 高い順(℃)", True),
    ])
    group("amedas_ranking_rain.png", [
        ("r1", "1時間降水量(mm)", True, 1, 0.5),
        ("r3", "3時間降水量(mm)", True, 1, 0.5),
        ("r12", "12時間降水量(mm)", True, 1, 0.5),
        ("r24", "24時間降水量(mm)", True, 1, 0.5),
    ])
    group("amedas_ranking_wind.png", [
        ("wmax", "最大風速(m/s)", True),
        ("hmin", "最小湿度(%)", False, 0),
        ("snow", "積雪深(cm)", True, 0, 1),
    ])
    return images


# =============================================================================
# 177chart.com の表示を撮影して配信する（2026-10-01〜）
#
# サイト側の表示(気象庁の公開APIをブラウザで描画)をそのまま撮影して配信画像にする。
# サイトが落ちている/Cloudflareに弾かれる/描画が終わらない等で撮影できなかった画像だけ、
# 従来のPillow描画(build_amedas_images)で補う。配信自体は止めない。
#   /amedas-akita/?view=shot   -> #ap177-shot        (秋田県の観測局一覧)
#   /amedas-ranking/?view=all  -> #ac177-g-temp/rain/wind (全国ランキング3枚)
# 描画が終わると、撮影対象の要素に data-ready="1" が付く(サイト側の約束)。
# =============================================================================

SITE_BASE = os.environ.get("SITE_BASE_URL", "https://177chart.com").rstrip("/")
SITE_SHOT_TOKEN = os.environ.get("SITE_SHOT_TOKEN", "").strip()   # Cloudflareで撮影用アクセスを許可する場合の合言葉(任意)
AMEDAS_USE_SITE = os.environ.get("AMEDAS_USE_SITE", "1").lower() in ("1", "true", "yes", "on")

# (URLパス, [(ファイル名, 撮影する要素のセレクタ), ...])
SITE_PAGES = [
    ("/amedas-akita/?view=shot", [("amedas_akita.png", "#ap177-shot")]),
    ("/amedas-ranking/?view=all", [
        ("amedas_ranking_temp.png", "#ac177-g-temp"),
        ("amedas_ranking_rain.png", "#ac177-g-rain"),
        ("amedas_ranking_wind.png", "#ac177-g-wind"),
    ]),
]
SITE_EXPECTED = [fn for _, tg in SITE_PAGES for fn, _ in tg]

# 撮影時に隠すサイトの部品(スクロールに追従して固定されるメニューやサイドバー、通知の案内などが、
# 撮影対象の要素に重なって写り込むのを防ぐ)
SITE_HIDE_CSS = """
#header, #header_main, #header_meta, .header_bg, #wpadminbar, .sidebar, aside, #footer, #socket,
#scroll-top-link, .av-burger-menu-main, #onesignal-slidedown-container, #onesignal-bell-container,
.onesignal-reset, .cmplz-cookiebanner, #cookie-notice { display: none !important; }
#ac177, #ap177 { max-width: none !important; width: auto !important; }
#ac177 th, #ap177 th { text-transform: none !important; letter-spacing: 0 !important; }
html, body { scroll-behavior: auto !important; }
"""


def screenshot_site() -> List[Tuple[str, bytes]]:
    """サイトのページを開いて、対象の要素を撮影する。撮れた分だけ返す(失敗は握りつぶさず表示する)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[WARN] playwright 未インストール — サイト撮影をスキップ")
        return []

    out: List[Tuple[str, bytes]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        headers = {"X-Shot-Token": SITE_SHOT_TOKEN} if SITE_SHOT_TOKEN else {}
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 1000},
            device_scale_factor=2,
            locale="ja-JP",
            extra_http_headers=headers,
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36 177chart-shot/1.0"),
        )
        for path, targets in SITE_PAGES:
            url = SITE_BASE + path
            page = ctx.new_page()
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=60_000)
                status = resp.status if resp else 0
                title = page.title()
                if status >= 400 or "Just a moment" in title or "Attention Required" in title:
                    raise RuntimeError(f"アクセスできない/Cloudflareの確認画面 (HTTP {status}, title={title!r})")
                page.locator('[data-ready="1"]').first.wait_for(timeout=90_000)
                page.add_style_tag(content=SITE_HIDE_CSS)
                page.wait_for_timeout(300)
                for fname, sel in targets:
                    el = page.locator(sel).first
                    el.wait_for(timeout=10_000)
                    png = el.screenshot()
                    print(f"[OK] site shot {fname}  {len(png):,} bytes  ({url})")
                    out.append((fname, png))
            except Exception as e:
                print(f"[WARN] サイト撮影失敗 {url}: {e}")
            finally:
                page.close()
        browser.close()
    return out


def collect_images() -> List[Tuple[str, bytes]]:
    """配信する画像を集める。サイトの撮影を優先し、撮れなかった分だけPillow描画で補う。"""
    shots: Dict[str, bytes] = {}
    if AMEDAS_USE_SITE:
        try:
            shots = dict(screenshot_site())
        except Exception as e:
            print(f"[WARN] サイト撮影で例外: {e}")
    missing = [fn for fn in SITE_EXPECTED if fn not in shots]
    fallback: Dict[str, bytes] = {}
    if missing:
        print(f"[INFO] サイトから撮れなかった画像をPillowで補う: {missing}")
        fallback = dict(build_amedas_images())
    images: List[Tuple[str, bytes]] = []
    for fn in SITE_EXPECTED:
        data = shots.get(fn) or fallback.get(fn)
        if data:
            images.append((fn, data))
    src = "サイト" if len(shots) == len(SITE_EXPECTED) else ("Pillow" if not shots else "サイト+Pillow")
    print(f"[INFO] 配信画像 {len(images)} 枚（元: {src}）")
    return images



def post_amedas_to_discord(images: List[Tuple[str, bytes]], when: datetime) -> None:
    """Discord #amedas へ、秋田県一覧とランキングの2メッセージで投稿。"""
    url = DISCORD_AMEDAS_WEBHOOK_URL
    if not url:
        print("[SKIP] DISCORD_AMEDAS_WEBHOOK_URL 未設定 — Discord 投稿をスキップ")
        return
    import uuid

    def post(files: List[Tuple[str, bytes]], content: str) -> None:
        if not files:
            return
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n\r\n'
                f'{json.dumps({"content": content, "flags": 4})}\r\n').encode()
        for i, (fname, data) in enumerate(files):
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; '
                     f'filename="{fname}"\r\nContent-Type: image/png\r\n\r\n').encode() + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(f"[Discord] POST {resp.status} ({content[:20]})")
        except Exception as e:
            print(f"[WARN] Discord POST 失敗: {e}")

    post([(f, b) for f, b in images if f.startswith("amedas_akita")],
         f"**アメダス観測値（秋田県）** {when.strftime('%m/%d %H:%M')}現在\n"
         f"🔗 [177chart 秋田県の一覧](<{SITE_BASE}/amedas-akita/>)　[アメダス（気象庁）](<{JMA_AMEDAS_URL}>)")
    post([(f, b) for f, b in images if f.startswith("amedas_ranking")],
         "**アメダスランキング（全国・当日0時〜最新の正時値）**\n"
         f"🔗 [177chart アメダスランキング](<{SITE_BASE}/amedas-ranking/>)")


def main_ranking(post_notion: bool = True) -> Tuple[List[Tuple[str, bytes]], List[str]]:
    """アメダス観測値・ランキング: JMA公開API → 画像 → R2 → Discord → Notion。"""
    jst_now = datetime.now(JST)
    images = collect_images()
    if not images:
        print("[INFO] アメダス画像なし — スキップ")
        return [], []

    r2_urls = _upload_r2(images, jst_now)
    post_amedas_to_discord(images, jst_now)

    if post_notion:
        _notion_write(
            title=f"アメダス観測値・ランキング / {jst_now.strftime('%m/%d %H:%M')}",
            r2_urls=r2_urls,
            jst_now=jst_now,
            yml_jst=_nearest_scheduled_slot_jst(jst_now, [6, 12, 18]),
        )
    return images, r2_urls


if __name__ == "__main__":
    main()
