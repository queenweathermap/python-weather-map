# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/msm_weather.py
#
# 気象庁のMSM(メソモデル)数値予報から、秋田県25市町村の「天気の目安」の表を描く。
#
# 以前、WCNの「分布予報(天気)」を撮影して配信していたが、WCNの停止で使えなくなった。
# 気象庁の天気分布予報(5kmメッシュ)は無料で取れないため、代わりにMSMの
# 「全雲量・1時間降水量・地上気温」を、市町村の位置の最寄りの格子点から取り出し、
# 3時間ごとの天気(晴・薄曇・曇・雨・雪など)に変換して表にする。
#
# ★これは気象庁が発表する天気予報ではない。MSMの値を当方の基準で天気に変換した
#   参考情報(目安)である。画像にその旨を必ず明記する。サイト等での一般公開はしない
#   (Discord・Notionのみ)。
#
# データ: 京都大学生存圏研究所のMSM GPVアーカイブ(気象庁の再配信、認証なし)
#   https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/YYYY/MM/DD/
#   Z__C_RJTD_{初期時刻UTC}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin / FH16-33 / FH34-39
# GRIB2の読み取りには pygrib を使う(pip install pygrib)。
# =============================================================================

from __future__ import annotations

import io
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

RISH_BASE = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
MSM_FILES = ["FH00-15", "FH16-33", "FH34-39"]
JST = timezone(timedelta(hours=9))

# MSM(格子): 北緯47.6〜22.4度を0.05度刻み(505点)、東経120〜150度を0.0625度刻み(481点)
LAT0, DLAT = 47.6, 0.05
LON0, DLON = 120.0, 0.0625
NLAT, NLON = 505, 481

# 秋田県25市町村の代表点(役所・役場付近。MSMは約5km格子なので数kmの誤差は問題にならない)
MUNICIPALITIES: List[Tuple[str, float, float]] = [
    ("秋田市", 39.7200, 140.1024), ("潟上市", 39.8747, 140.0619), ("男鹿市", 39.8853, 139.8474),
    ("五城目町", 39.9472, 140.1131), ("八郎潟町", 39.9450, 140.0972), ("井川町", 39.9139, 140.0917),
    ("大潟村", 39.9800, 140.0100), ("能代市", 40.2131, 140.0261), ("三種町", 40.0944, 140.0197),
    ("八峰町", 40.3986, 140.0111), ("由利本荘市", 39.3864, 140.0489), ("にかほ市", 39.2867, 139.9061),
    ("大館市", 40.2719, 140.5644), ("小坂町", 40.3089, 140.7714), ("北秋田市", 40.2264, 140.3700),
    ("上小阿仁村", 39.9944, 140.3611), ("藤里町", 40.2650, 140.2300), ("鹿角市", 40.2167, 140.7864),
    ("仙北市", 39.7061, 140.7219), ("大仙市", 39.4531, 140.4756), ("横手市", 39.3131, 140.5664),
    ("湯沢市", 39.1642, 140.4942), ("美郷町", 39.4400, 140.5600), ("羽後町", 39.2000, 140.4300),
    ("東成瀬村", 39.1400, 140.7850),
]

# 天気の目安の判定(3時間ごと)
RAIN_MM_3H = 0.5        # 3時間降水量がこれ以上なら、雨/雪/みぞれ
HEAVY_MM_3H = 10.0      # これ以上は「強い雨」
SNOW_T_C = 1.0          # 気温がこれ以下なら雪
SLEET_T_C = 3.0         # 気温がこれ以下(雪より上)ならみぞれ
CLOUD_CLEAR = 25.0      # 全雲量(%)がこれ未満なら「晴」
CLOUD_CLOUDY = 75.0     # これ以上なら「曇」。間は「薄曇(晴時々曇)」


def _idx(lat: float, lon: float) -> Tuple[int, int]:
    i = int(round((LAT0 - lat) / DLAT))
    j = int(round((lon - LON0) / DLON))
    return min(max(i, 0), NLAT - 1), min(max(j, 0), NLON - 1)


# -----------------------------------------------------------------------------
# データ取得
# -----------------------------------------------------------------------------

def _list_inits(day: datetime) -> Dict[str, List[str]]:
    """その日(UTC)のディレクトリを読み、MSM地上の3ファイルが揃っている初期時刻(14桁)→ファイル名を返す。"""
    url = f"{RISH_BASE}/{day:%Y/%m/%d}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "akita-guidance-bot/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"[WARN] MSM一覧の取得失敗: {e} ({url})")
        return {}
    names = set(re.findall(r"Z__C_RJTD_(\d{14})_MSM_GPV_Rjp_Lsurf_(FH[\d-]+)_grib2\.bin", html))
    by_init: Dict[str, List[str]] = {}
    for ts, fh in names:
        by_init.setdefault(ts, []).append(fh)
    return {ts: sorted(v) for ts, v in by_init.items() if all(f in v for f in MSM_FILES)}


def find_latest_init(now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """RISHで、3つのファイルが揃っている最新の初期時刻(UTC)を探す(当日→前日の順)。"""
    now_utc = now_utc or datetime.now(timezone.utc)
    for back in (0, 1):
        inits = _list_inits(now_utc - timedelta(days=back))
        if inits:
            ts = sorted(inits)[-1]
            return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return None


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "akita-guidance-bot/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def load_point_series(init: datetime) -> Dict[str, Dict[int, List[float]]]:
    """市町村ごとの時系列を返す: {"t": {FT: [℃...]}, "tc": {FT: [%...]}, "p1": {FT(終了時刻): [mm...]}}。
    リストの順序は MUNICIPALITIES と同じ。"""
    import pygrib  # noqa: WPS433 (依存が無い環境ではimport時に失敗させて呼び出し側でスキップする)

    pts = [_idx(la, lo) for _, la, lo in MUNICIPALITIES]
    ii = [p[0] for p in pts]
    jj = [p[1] for p in pts]
    out: Dict[str, Dict[int, List[float]]] = {"t": {}, "tc": {}, "p1": {}}
    ts = init.strftime("%Y%m%d%H%M%S")
    day = f"{init:%Y/%m/%d}"
    with tempfile.TemporaryDirectory() as tmp:
        for fh in MSM_FILES:
            name = f"Z__C_RJTD_{ts}_MSM_GPV_Rjp_Lsurf_{fh}_grib2.bin"
            path = os.path.join(tmp, name)
            print(f"[INFO] MSM取得: {name}")
            _download(f"{RISH_BASE}/{day}/{name}", path)
            g = pygrib.open(path)
            for m in g:
                cat, num = m.parameterCategory, m.parameterNumber
                if (cat, num) == (0, 0) and m.typeOfLevel == "heightAboveGround":      # 気温(K)
                    out["t"][m.forecastTime] = [float(m.values[i, j]) - 273.15 for i, j in pts]
                elif (cat, num) == (6, 1):                                              # 全雲量(%)
                    out["tc"][m.forecastTime] = [float(m.values[i, j]) for i, j in pts]
                elif (cat, num) == (1, 8):                                              # 1時間降水量(mm)。stepRangeは"3-4"(3〜4時間)
                    end = int(str(m.stepRange).split("-")[-1])
                    out["p1"][end] = [float(m.values[i, j]) for i, j in pts]
            g.close()
    return out


# -----------------------------------------------------------------------------
# 天気の目安への変換
# -----------------------------------------------------------------------------

def classify(precip3h: float, temp_c: float, cloud_pct: float) -> str:
    """3時間ごとの天気の目安。戻り値: clear / partly / cloudy / rain / heavy / sleet / snow"""
    if precip3h >= RAIN_MM_3H:
        if temp_c <= SNOW_T_C:
            return "snow"
        if temp_c <= SLEET_T_C:
            return "sleet"
        return "heavy" if precip3h >= HEAVY_MM_3H else "rain"
    if cloud_pct < CLOUD_CLEAR:
        return "clear"
    if cloud_pct >= CLOUD_CLOUDY:
        return "cloudy"
    return "partly"


LABEL = {"clear": "晴れ", "partly": "薄曇り", "cloudy": "曇り", "rain": "雨", "heavy": "強い雨", "sleet": "みぞれ", "snow": "雪"}


def build_grid(series: Dict[str, Dict[int, List[float]]], init: datetime, max_ft: int = 39):
    """FT=3,6,...,max_ft の3時間ごとの天気(市町村×時刻)と、JST日付ごとの最高・最低気温を作る。"""
    fts = [ft for ft in range(3, max_ft + 1, 3) if ft in series["t"] and ft in series["tc"]]
    cells: List[List[str]] = []
    for k in range(len(MUNICIPALITIES)):
        row = []
        for ft in fts:
            p3 = sum(series["p1"].get(h, [0.0] * len(MUNICIPALITIES))[k] for h in (ft - 2, ft - 1, ft))
            row.append(classify(p3, series["t"][ft][k], series["tc"][ft][k]))
        cells.append(row)
    # JST日付ごとの最高・最低(1時間ごとの気温の、予報期間内の値。一部の時間しか無い日は partial=True)
    days: Dict[str, Dict[str, object]] = {}
    for ft, vals in series["t"].items():
        d = (init + timedelta(hours=ft)).astimezone(JST)
        key = d.strftime("%Y-%m-%d")
        rec = days.setdefault(key, {"hours": set(), "vals": [[] for _ in MUNICIPALITIES], "date": d})
        rec["hours"].add(d.hour)
        for k, v in enumerate(vals):
            rec["vals"][k].append(v)
    return fts, cells, days


# -----------------------------------------------------------------------------
# 描画
# -----------------------------------------------------------------------------

def render(init: datetime, fts, cells, days) -> bytes:
    from PIL import Image, ImageDraw
    from module.jobs.amedas import _load_fonts, C_TITLE_BG, C_TITLE_FG, C_HEADER_BG, C_HEADER_FG, C_ROW_ODD, C_ROW_EVEN, C_BORDER, C_TEXT

    f_sm, _, f_lg = _load_fonts()
    if f_sm is None:
        raise ImportError("Pillow not available")
    day_keys = sorted(days)[:3]
    NAME_W, CELL_W, ROW_H, HDR_H, TTL_H, TMP_W = 92, 46, 28, 44, 34, 58
    ncol = len(fts)
    width = NAME_W + CELL_W * ncol + TMP_W * 2 * len(day_keys) + 2
    NOTE_H = 66
    height = TTL_H + HDR_H + ROW_H * len(MUNICIPALITIES) + NOTE_H + 1
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)

    init_jst = init.astimezone(JST)
    d.rectangle([(0, 0), (width, TTL_H)], fill=C_TITLE_BG)
    d.text((10, (TTL_H - 15) // 2),
           f"MSM 天気の目安（秋田県 市町村）　初期値 {init_jst:%m/%d %H時}JST　※気象庁の天気予報ではありません", fill=C_TITLE_FG, font=f_lg)

    # ヘッダー(日付・時刻)
    y0 = TTL_H
    d.rectangle([(0, y0), (width, y0 + HDR_H)], fill=C_HEADER_BG)
    d.text((8, y0 + 14), "市町村", fill=C_HEADER_FG, font=f_sm)
    x = NAME_W
    for ft in fts:
        t = (init + timedelta(hours=ft)).astimezone(JST)
        d.text((x + 6, y0 + 4), f"{t.day}日" if (t.hour == 3 or ft == fts[0]) else "", fill=C_HEADER_FG, font=f_sm)
        d.text((x + 8, y0 + 24), f"{t.hour:02d}時", fill=C_HEADER_FG, font=f_sm)
        x += CELL_W
    for key in day_keys:
        dd = days[key]["date"]
        partial = len(days[key]["hours"]) < 24
        d.text((x + 6, y0 + 4), f"{dd.day}日{'*' if partial else ''}", fill=C_HEADER_FG, font=f_sm)
        d.text((x + 6, y0 + 24), "最高", fill=C_HEADER_FG, font=f_sm)
        d.text((x + TMP_W + 6, y0 + 24), "最低", fill=C_HEADER_FG, font=f_sm)
        x += TMP_W * 2

    def symbol(cx: int, cy: int, kind: str) -> None:
        r = 9
        box = [cx - r, cy - r, cx + r, cy + r]
        if kind == "clear":
            d.ellipse(box, fill=(255, 122, 26), outline=(200, 90, 10))
        elif kind == "partly":       # 晴+曇の半々
            d.ellipse(box, fill=(255, 122, 26), outline=(200, 90, 10))
            d.pieslice(box, 270, 90, fill=(170, 176, 184))
        elif kind == "cloudy":
            d.ellipse(box, fill=(170, 176, 184), outline=(120, 126, 134))
        elif kind == "rain":
            d.ellipse(box, fill=(46, 134, 222), outline=(20, 90, 170))
        elif kind == "heavy":
            d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(20, 60, 170), outline=(10, 30, 110))
        elif kind == "sleet":
            d.ellipse(box, fill=(150, 110, 220), outline=(100, 70, 170))
        elif kind == "snow":
            d.ellipse(box, fill=(255, 255, 255), outline=(60, 170, 220), width=3)

    y = y0 + HDR_H
    for k, (name, _, _) in enumerate(MUNICIPALITIES):
        d.rectangle([(0, y), (width, y + ROW_H)], fill=C_ROW_ODD if k % 2 == 0 else C_ROW_EVEN)
        d.line([(0, y), (width, y)], fill=C_BORDER)
        d.text((8, y + 6), name, fill=C_TEXT, font=f_sm)
        x = NAME_W
        for kind in cells[k]:
            symbol(x + CELL_W // 2, y + ROW_H // 2, kind)
            x += CELL_W
        for key in day_keys:
            vals = days[key]["vals"][k]
            hi, lo = max(vals), min(vals)
            d.text((x + TMP_W - 8 - 30, y + 6), f"{hi:.0f}℃", fill=(200, 30, 30), font=f_sm)
            d.text((x + TMP_W * 2 - 8 - 30, y + 6), f"{lo:.0f}℃", fill=(30, 70, 200), font=f_sm)
            x += TMP_W * 2
        y += ROW_H
    # 縦線
    x = NAME_W
    for _ in fts:
        d.line([(x, y0 + HDR_H), (x, y)], fill=C_BORDER)
        x += CELL_W
    d.line([(x, y0), (x, y)], fill=C_BORDER)

    # 凡例と但し書き
    ny = y + 6
    lx = 8
    for kind in ("clear", "partly", "cloudy", "rain", "heavy", "sleet", "snow"):
        symbol(lx + 9, ny + 9, kind)
        d.text((lx + 24, ny + 2), LABEL[kind], fill=C_TEXT, font=f_sm)
        lx += 24 + 14 * len(LABEL[kind]) + 18
    d.text((8, ny + 24), "気象庁のMSM(数値予報)の全雲量・降水量・気温を、当方の基準で天気に変換した参考の目安です。気象庁発表の天気予報とは異なります。", fill=(90, 90, 90), font=f_sm)
    d.text((8, ny + 42), "*は予報期間内の一部の時間だけの最高・最低。降水量0.5mm/3時間以上で雨(気温3℃以下でみぞれ、1℃以下で雪)。防災の判断には気象庁の発表をご利用ください。", fill=(90, 90, 90), font=f_sm)
    d.rectangle([(0, 0), (width - 1, height - 1)], outline=C_BORDER)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_msm_weather() -> Optional[Tuple[bytes, datetime]]:
    """MSMから作った秋田県市町村の天気の目安の画像と、初期時刻(UTC)を返す。取得や解析に失敗したら None。"""
    try:
        import pygrib  # noqa: F401
    except ImportError:
        print("[WARN] pygrib 未インストール — MSM天気の目安をスキップ")
        return None
    init = find_latest_init()
    if not init:
        print("[WARN] MSMの初期時刻が見つからない")
        return None
    series = load_point_series(init)
    fts, cells, days = build_grid(series, init)
    if not fts:
        print("[WARN] MSMから時系列を作れなかった")
        return None
    return render(init, fts, cells, days), init
