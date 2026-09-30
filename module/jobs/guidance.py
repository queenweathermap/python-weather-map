# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# 気象庁(JMA)の公開データから秋田県のガイダンス表を描画し、Discord(#guidance)へ
# 投稿する。Notion資料アーカイブDB(NOTION_DATABASE_ID)にも1件にまとめて記録する。
#
# 2026-09-30: WCN(Weathercaster.jp)サーバ停止により、従来のWCN会員ページの
# スクリーンショット方式(MSM府県時別・分布予報・週間ガイダンス)から、JMA元データの
# 自前描画に置き換えた。認証・Playwright不要(標準ライブラリ + Pillow)。
#
# 出力:
#   guid_msm_rain.png  MSM 降水ガイダンス(沿岸/内陸 × 1h/3h/24h × 上位/中位/下位) + 発雷確率
#   guid_msm_wind.png  MSM 風ガイダンス(秋田県のアメダス各地点)
#   guid_short.png     短期予報(天気・風・降水確率・気温)
#   guid_week.png      週間予報(天気・降水確率・信頼度・最高/最低気温と予測幅)
# WCNにあった気温・天気・日照などの地点別MSM時別ガイダンスと分布予報は、JMAが
# 公開していない(または認証付き)ため再現できない。
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
DISCORD_GUIDANCE_WEBHOOK_URL = os.environ.get("DISCORD_GUIDANCE_WEBHOOK_URL", "")

JMA_ADV_DATA = "https://www.jma.go.jp/bosai/advisor/data"
JMA_FORECAST_JSON = "https://www.jma.go.jp/bosai/forecast/data/forecast/050000.json"
AMEDAS_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
JMA_FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code=050000"

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "guidance").strip().strip("/")

JST = timezone(timedelta(hours=9))

REGIONS = [("050010", "沿岸"), ("050020", "内陸")]
# filterN = 確率レベル。0が最も大きい側(上位)、4が最も小さい側。
FILTERS = [("filter0", "上位"), ("filter2", "中位"), ("filter4", "下位")]

WIND_DIR_JP = {
    "N": "北", "NNE": "北北東", "NE": "北東", "ENE": "東北東", "E": "東", "ESE": "東南東",
    "SE": "南東", "SSE": "南南東", "S": "南", "SSW": "南南西", "SW": "南西", "WSW": "西南西",
    "W": "西", "WNW": "西北西", "NW": "北西", "NNW": "北北西",
}

# 天気コード → 短い天気文言(主要コードのみ。無ければ先頭桁で大分類)
WEATHER_TEXT = {
    "100": "晴", "101": "晴時々曇", "102": "晴一時雨", "103": "晴時々雨", "104": "晴一時雪",
    "105": "晴時々雪", "110": "晴のち時々曇", "111": "晴のち曇", "112": "晴のち一時雨",
    "113": "晴のち時々雨", "114": "晴のち雨", "115": "晴のち一時雪", "116": "晴のち時々雪",
    "117": "晴のち雪", "200": "曇", "201": "曇時々晴", "202": "曇一時雨", "203": "曇時々雨",
    "204": "曇一時雪", "205": "曇時々雪", "206": "曇時々雨か雪", "207": "曇時々雨か雪",
    "210": "曇のち時々晴", "211": "曇のち晴", "212": "曇のち一時雨", "213": "曇のち時々雨",
    "214": "曇のち雨", "215": "曇のち一時雪", "216": "曇のち時々雪", "217": "曇のち雪",
    "218": "曇のち雨か雪", "300": "雨", "301": "雨時々晴", "302": "雨時々止む", "303": "雨時々雪",
    "308": "大雨", "311": "雨のち晴", "313": "雨のち曇", "314": "雨のち時々雪", "315": "雨のち雪",
    "400": "雪", "401": "雪時々晴", "402": "雪時々止む", "403": "雪時々雨", "406": "暴風雪",
    "411": "雪のち晴", "413": "雪のち曇", "414": "雪のち雨",
}
WEATHER_FALLBACK = {"1": "晴系", "2": "曇系", "3": "雨系", "4": "雪系"}

# 画像スタイル(module/jobs/amedas.py の表と揃える)
RAIN_COLORS = [(50, (230, 80, 160)), (30, (255, 130, 130)), (20, (255, 190, 120)),
               (10, (255, 240, 150)), (5, (160, 200, 255)), (1, (220, 235, 255))]
WIND_COLORS = [(15, (255, 130, 130)), (10, (255, 190, 120)), (5, (255, 240, 150))]
POT_COLORS = [(50, (255, 190, 120)), (30, (255, 240, 150)), (10, (255, 250, 210))]


# =============================================================================
# ユーティリティ
# =============================================================================

def _jst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def _nearest_scheduled_slot_jst(now: datetime, hours: List[int]) -> datetime:
    """実行が数分遅れても、yml上の狙い撃ちスケジュール時刻(例: 04:00/16:00)
    ぴったりの表示にする。ヘッダ表示用。"""
    best_h = min(hours, key=lambda h: min(abs(now.hour - h), 24 - abs(now.hour - h)))
    return now.replace(hour=best_h, minute=0, second=0, microsecond=0)


def _get_json(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "akita-guidance-bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] fetch失敗: {e} ({url})")
        return None


def _shade(v: Optional[float], scale) -> Optional[Tuple[int, int, int]]:
    if v is None:
        return None
    for th, col in scale:
        if v >= th:
            return col
    return None


def _draw(title, headers, rows, right, colors=None) -> bytes:
    from module.jobs.amedas import _draw_table_img
    return _draw_table_img(title, headers, rows, right_align_cols=right, cell_colors=colors)


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _latest_run(kind: str, model: str, elem: str) -> Optional[datetime]:
    """time_{model}_{elem}.json から最新の初期時刻(UTC)を返す。
    ※ファイル名に使うのはUTC正規化した14桁。'+00:00' の数字を拾わないこと。"""
    raw = _get_json(f"{JMA_ADV_DATA}/{kind}/time_{model}_{elem}.json")
    if not raw:
        return None
    return datetime.fromisoformat(str(raw["time"]).replace("Z", "+00:00")).astimezone(timezone.utc)


def _frame_labels(init_utc: datetime, n: int, start_ft: int = 3, step: int = 3) -> List[str]:
    """MSM 3時間刻みのコマ見出し(JST、'd日HH')。先頭は初期時刻+3時間と推定
    (風の実況との相関から。ガイダンス表の見出しが公開されていないための推定)。"""
    out = []
    for k in range(n):
        t = (init_utc + timedelta(hours=start_ft + step * k)).astimezone(JST)
        out.append(f"{t.day}日{t.hour:02d}時")
    return out


# =============================================================================
# [1] MSM 降水ガイダンス(沿岸/内陸) + 発雷確率
# =============================================================================

def build_msm_rain() -> Optional[Tuple[bytes, datetime]]:
    init = _latest_run("guid_table", "msm", "rain")
    if not init:
        return None
    ts = init.strftime("%Y%m%d%H%M%S")
    rain = _get_json(f"{JMA_ADV_DATA}/guid_table/{ts}_msm_rain.json")
    pot = _get_json(f"{JMA_ADV_DATA}/guid_table/{ts}_msm_pot.json")
    if not rain:
        return None
    n = len(next(iter(rain["rain3"]["filter0"].values())))
    labels = _frame_labels(init, n)
    headers = ["区域", "要素", "確率"] + labels

    rows: List[List[str]] = []
    colors: Dict[Tuple[int, int], Tuple[int, int, int]] = {}

    def add(region, elem_label, flt_label, vals, scale, offset=0):
        r = len(rows)
        row = [region, elem_label, flt_label] + [""] * n
        for i, v in enumerate(vals):
            ci = 3 + offset + i
            if ci >= len(row):
                break
            row[ci] = f"{v:g}"
            c = _shade(_num(v), scale)
            if c:
                colors[(r, ci)] = c
        rows.append(row)

    for code, name in REGIONS:
        for key, lbl in (("rain3", "3時間雨量mm"), ("rain1", "1時間雨量mm"), ("rain24", "24時間雨量mm")):
            block = rain.get(key, {})
            for fkey, flabel in FILTERS:
                vals = block.get(fkey, {}).get(code)
                if not vals:
                    continue
                # 24時間雨量は先頭を欠いて末尾に揃う(FT=24〜39時間の6コマ)
                add(name, lbl, flabel, vals, RAIN_COLORS, offset=n - len(vals) if key == "rain24" else 0)
        if pot:
            for fkey, flabel in FILTERS[:2]:
                vals = pot.get("pot", {}).get(fkey, {}).get(code)
                if vals:
                    add(name, "発雷確率%", flabel, vals, POT_COLORS)

    title = f"MSM ガイダンス 降水・発雷（秋田県）  初期値 {init.astimezone(JST).strftime('%m/%d %H時')}JST"
    return _draw(title, headers, rows, set(range(3, 3 + n)), colors), init


# =============================================================================
# [2] MSM 風ガイダンス(アメダス地点)
# =============================================================================

def build_msm_wind() -> Optional[Tuple[bytes, datetime]]:
    init = _latest_run("guid_table_wind", "msm", "wind")
    if not init:
        return None
    ts = init.strftime("%Y%m%d%H%M%S")
    wind = _get_json(f"{JMA_ADV_DATA}/guid_table_wind/{ts}_msm_wind.json")
    table = _get_json(AMEDAS_TABLE_URL) or {}
    if not wind:
        return None
    areas = sorted((a for a in wind["areas"] if a["stationCode"].startswith("32")),
                   key=lambda a: a["stationCode"])
    if not areas:
        return None
    n = len(areas[0]["windSpeeds"])
    headers = ["地点"] + _frame_labels(init, n)
    rows, colors = [], {}
    for r, a in enumerate(areas):
        row = [table.get(a["stationCode"], {}).get("kjName", a["stationCode"])]
        for i in range(n):
            sp = _num(a["windSpeeds"][i])
            d = WIND_DIR_JP.get(a["windDirections"][i], "")
            row.append(f"{d} {sp:g}" if sp is not None else "---")
            c = _shade(sp, WIND_COLORS)
            if c:
                colors[(r, i + 1)] = c
        rows.append(row)
    title = f"MSM ガイダンス 風向・風速m/s（秋田県）  初期値 {init.astimezone(JST).strftime('%m/%d %H時')}JST"
    return _draw(title, headers, rows, set(range(1, n + 1)), colors), init


# =============================================================================
# [3] 短期予報・週間予報(気象庁 府県天気予報 公開JSON)
# =============================================================================

def _wx(code: str) -> str:
    if not code:
        return "---"
    return WEATHER_TEXT.get(code) or WEATHER_FALLBACK.get(code[:1], code)


def _md(iso: str) -> str:
    t = datetime.fromisoformat(iso).astimezone(JST)
    return f"{t.month}/{t.day}({'月火水木金土日'[t.weekday()]})"


def _dh(iso: str) -> str:
    t = datetime.fromisoformat(iso).astimezone(JST)
    return f"{t.day}日{t.hour:02d}時"


def _tlabel(iso: str) -> str:
    """気温予報の時刻定義: 00時=朝の最低、09時=日中の最高。"""
    t = datetime.fromisoformat(iso).astimezone(JST)
    return f"{t.month}/{t.day}{'最高' if t.hour == 9 else '最低'}"


def build_short(fc) -> Optional[bytes]:
    short = fc[0]
    weather = short["timeSeries"][0]
    pops = short["timeSeries"][1]
    temps = short["timeSeries"][2]

    headers = ["区域", "日", "天気", "風"]
    rows = []
    for a in weather["areas"]:
        for i, td in enumerate(weather["timeDefines"]):
            rows.append([
                a["area"]["name"], _md(td), a.get("weathers", [""] * 3)[i].replace("　", ""),
                a.get("winds", [""] * 3)[i].replace("　", ""),
            ])
    img1 = _draw(f"短期予報（秋田県）  {_md(short['reportDatetime'])} {short['publishingOffice']}発表",
                 headers, rows, set())

    # 降水確率(6時間毎)・地点気温
    ph = ["区域"] + [_dh(t) for t in pops["timeDefines"]]
    prow, pcol = [], {}
    for r, a in enumerate(pops["areas"]):
        prow.append([a["area"]["name"]] + [f"{p}%" if p != "" else "---" for p in a["pops"]])
        for ci, p in enumerate(a["pops"], 1):
            c = _shade(_num(p), POT_COLORS)
            if c:
                pcol[(r, ci)] = c
    img2 = _draw("降水確率（6時間毎）", ph, prow, set(range(1, len(ph))), pcol)

    th = ["地点"] + [_tlabel(t) for t in temps["timeDefines"]]
    trow = [[a["area"]["name"]] + [f"{v}℃" if v != "" else "---" for v in a["temps"]] for a in temps["areas"]]
    img3 = _draw("気温予報（最低=朝の最低気温 / 最高=日中の最高気温）", th, trow, set(range(1, len(th))))

    try:
        from PIL import Image
        imgs = [Image.open(io.BytesIO(b)).convert("RGB") for b in (img1, img2, img3)]
        w = max(i.width for i in imgs)
        h = sum(i.height for i in imgs) + 8 * (len(imgs) - 1)
        canvas = Image.new("RGB", (w, h), (220, 220, 220))
        y = 0
        for im in imgs:
            canvas.paste(im, (0, y))
            y += im.height + 8
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] 短期予報 合成失敗: {e}")
        return img1


def build_week(fc) -> Optional[bytes]:
    week = fc[1]
    wx, tp = week["timeSeries"][0], week["timeSeries"][1]
    w = wx["areas"][0]
    t = tp["areas"][0]

    def rng(vals, up, lo, i):
        v = vals[i] if i < len(vals) else ""
        if v == "":
            return "---"
        u = up[i] if i < len(up) else ""
        l = lo[i] if i < len(lo) else ""
        return f"{v} ({l}〜{u})" if u != "" and l != "" else v

    headers = ["日", "天気", "降水確率", "信頼度", "最高℃ (予測幅)", "最低℃ (予測幅)"]
    rows, colors = [], {}
    for i, td in enumerate(wx["timeDefines"]):
        pop = w["pops"][i] if i < len(w["pops"]) else ""
        rows.append([
            _md(td), _wx(w["weatherCodes"][i]), f"{pop}%" if pop != "" else "---",
            (w["reliabilities"][i] if i < len(w["reliabilities"]) else "") or "---",
            rng(t["tempsMax"], t["tempsMaxUpper"], t["tempsMaxLower"], i),
            rng(t["tempsMin"], t["tempsMinUpper"], t["tempsMinLower"], i),
        ])
        c = _shade(_num(pop), POT_COLORS)
        if c:
            colors[(i, 2)] = c
    return _draw(f"週間予報（秋田県・{t['area']['name']}）  {_md(week['reportDatetime'])} {week['publishingOffice']}発表",
                 headers, rows, {2, 3, 4, 5}, colors)


def build_images() -> Tuple[List[Tuple[str, bytes]], Optional[datetime]]:
    images: List[Tuple[str, bytes]] = []
    init = None
    for fname, fn in (("guid_msm_rain.png", build_msm_rain), ("guid_msm_wind.png", build_msm_wind)):
        try:
            res = fn()
            if res:
                images.append((fname, res[0]))
                init = init or res[1]
        except Exception as e:
            print(f"[WARN] {fname} 生成失敗: {e}")

    fc = _get_json(JMA_FORECAST_JSON)
    if fc and len(fc) >= 2:
        for fname, fn in (("guid_short.png", build_short), ("guid_week.png", build_week)):
            try:
                img = fn(fc)
                if img:
                    images.append((fname, img))
            except Exception as e:
                print(f"[WARN] {fname} 生成失敗: {e}")
    return images, init


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

    day_hm = _jst_now().strftime("%Y%m%d/%H%M")
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
# Discord 投稿
# =============================================================================

def _post_images_bulk(images: List[Tuple[str, bytes]], content: str = "") -> None:
    """(filename, bytes) リストを最大10枚ずつ Discord に投稿する。"""
    if not DISCORD_GUIDANCE_WEBHOOK_URL or not images:
        return

    chunk_size = 10
    for chunk_start in range(0, len(images), chunk_size):
        chunk = images[chunk_start: chunk_start + chunk_size]
        boundary = f"----GuidanceBotBulk{chunk_start}"
        payload = {
            "content": content if chunk_start == 0 else "",
            "flags": 4,
            "attachments": [{"id": i, "filename": fn} for i, (fn, _) in enumerate(chunk)],
        }

        def _part_json(d: str) -> bytes:
            h = (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="payload_json"\r\n'
                 f"Content-Type: application/json\r\n\r\n")
            return h.encode() + d.encode() + b"\r\n"

        def _part_file(i: int, data: bytes, name: str) -> bytes:
            h = (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="files[{i}]"; filename="{name}"\r\n'
                 f"Content-Type: image/png\r\n\r\n")
            return h.encode() + data + b"\r\n"

        body = _part_json(json.dumps(payload))
        for i, (fn, data) in enumerate(chunk):
            body += _part_file(i, data, fn)
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            DISCORD_GUIDANCE_WEBHOOK_URL, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent":   "akita-guidance-bot/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"[OK] Discord bulk HTTP {r.status} ({len(chunk)} files)")
        except Exception as e:
            print(f"[ERR] Discord bulk post: {e}")


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Guidance (JMA data) ===")

    images, init = build_images()
    if not images:
        print("[INFO] ガイダンス画像なし（スキップ）")
        print("=== Done ===")
        return

    urls = _upload_r2(images)
    init_txt = init.astimezone(JST).strftime("%m/%d %H時") if init else "不明"
    _post_images_bulk(
        images,
        content=(f"**ガイダンス（秋田県）** MSM初期値 {init_txt}JST\n"
                 f"🔗 [気象庁 秋田県天気予報](<{JMA_FORECAST_URL}>)"),
    )

    # Notion資料アーカイブDBへ1件にまとめて記録する（Discord/PWAとは独立、
    # R2の保存期限が切れても内容が残るように）。
    try:
        from module.utils.notion_utils import (
            create_db_row,
            append_heading,
            append_imported_images_from_urls,
            append_images,
            append_bookmark,
        )

        jst_now = _jst_now()
        slot_jst = _nearest_scheduled_slot_jst(jst_now, [4, 16])
        cover_url = next((u for u in urls if u), "")
        page_id = create_db_row(
            title=f"Guidance　ガイダンス〔{slot_jst.strftime('%Y%m%d %H:%M')}〕",
            category="Guidance",
            init_jst_iso=jst_now.isoformat(),
            r2_url=cover_url,
            autogen=True,
            pwa=False,
            icon_emoji="🧭",
            cover_url=cover_url,
            yml_iso=slot_jst.isoformat(),
        )

        if page_id:
            append_bookmark(page_id, JMA_FORECAST_URL, caption="気象庁 秋田県天気予報")
            ok_urls = [u for u in urls if u]
            if ok_urls:
                append_heading(page_id, "MSMガイダンス・短期予報・週間予報（秋田県）", level=2)
                items = [(f"{i + 1:02d}.png", u, "image/png") for i, u in enumerate(ok_urls)]
                try:
                    append_imported_images_from_urls(page_id, items, chunk=10)
                except Exception as e:
                    print(f"[WARN] Notion画像インポート失敗、外部リンクにフォールバック: {e}")
                    append_images(page_id, ok_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] Notionアーカイブ失敗: {e}")

    print("=== Done ===")


if __name__ == "__main__":
    main()
