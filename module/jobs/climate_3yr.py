# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/climate_3yr.py
#
# 過去3年 気象データ比較グラフ（秋田県3地点: 鷹巣 / 秋田 / 横手）
#
#   ・予報ではなく「観測実績（参照データ）」の扱い。
#   ・日最高気温 / 日最低気温 / 最深積雪 を、前半(1〜15)/後半(16〜末) で作図。
#   ・過去3年（対象年の前3年）を重ねて 3地点×3項目 の 3×3 グラフを1枚のPNGに。
#   ・出力 PNG → R2（任意）→ Discord 専用チャンネル。
#
# データ源:
#   気象庁「過去の気象データ検索(etrn)」の日別表
#     気象官署 : view/daily_s1.php
#     アメダス : view/daily_a1.php
#
# 方針:
#   ・SNS(X/Bluesky/Threads)は当面手動。まずは画像生成＋Discord投稿を自動化する。
#   ・最深積雪の「平年値線」は無し。気温の平年線もv1では出さない（後日 SHOW_TEMP_NORMAL で拡張可）。
# =============================================================================

from __future__ import annotations

import calendar
import io
import math
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


# =============================================================================
# 観測所設定
#   (表示名, prec_no, block_no, kind)   kind: "s1"=気象官署 / "a1"=アメダス
#   3地点とも etrn 実ページで確認済み。地点を足したい場合は
#   etrn の日別表 URL の block_no をそのまま追記する（空 "" の局は安全にスキップ）。
# =============================================================================
STATIONS: List[Tuple[str, str, str, str]] = [
    ("鷹巣", "32", "0184", "a1"),    # 確認済（アメダス）
    ("秋田", "32", "47582", "s1"),   # 気象官署
    ("横手", "32", "0198", "a1"),    # 確認済（アメダス）
]

# 3項目（内部キー, 列見出し）
ELEMENTS = [
    ("tmax", "最高気温 (℃)"),
    ("tmin", "最低気温 (℃)"),
    ("snow", "最深積雪 (cm)"),
]

# 最深積雪の列を出す月（12〜3月のみ）。それ以外は気温2列だけにする。
SNOW_MONTHS = {12, 1, 2, 3}


def elements_for_month(month: int):
    """対象月に応じて描画する項目を返す（積雪は12〜3月のみ）。"""
    return [e for e in ELEMENTS if e[0] != "snow" or month in SNOW_MONTHS]

# 年ごとの色（新しい年→青 / 中→金 / 古→赤：お手本に合わせる）
YEAR_COLORS = ["#1f6fd6", "#eaa800", "#e0331f"]

ETRN_BASE = "https://www.data.jma.go.jp/obd/stats/etrn/view"
UA = {"User-Agent": "Mozilla/5.0 climate-3yr-bot/1.0", "Accept-Language": "ja,en;q=0.8"}

JST = timezone(timedelta(hours=9))

# 拡張フラグ（v1は気温平年線オフ）
SHOW_TEMP_NORMAL = os.environ.get("CLIMATE_SHOW_TEMP_NORMAL", "0").lower() in ("1", "true", "yes", "on")

# R2 / Discord
R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
DISCORD_ENABLE = os.environ.get("DISCORD_ENABLE", "1").lower() in ("1", "true", "yes", "on")


def discord_webhook_url() -> str:
    return (
        os.environ.get("DISCORD_CLIMATE_WEBHOOK_URL", "").strip()
        or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    )


# =============================================================================
# 対象期間（前半/後半）の決定
# =============================================================================
def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def resolve_window() -> Tuple[int, int, int, int, List[int]]:
    """
    対象の (year, month, start_day, end_day, comparison_years) を返す。

    ・env で明示指定できる:
        CLIMATE_TARGET_YEAR, CLIMATE_TARGET_MONTH, CLIMATE_TARGET_HALF(first/second)
    ・未指定なら JST の実行日から自動決定:
        1〜15日 → 当月 前半(1〜15)
        16日〜  → 当月 後半(16〜末日)
    比較する過去3年は、対象年の前3年 [year-1, year-2, year-3]。
    （対象期間は "これから" の旬でも、過去3年ぶんは実績が揃っているため先出しできる）
    """
    n = now_jst()

    # env は workflow_dispatch 未入力時に空文字 "" で来るため、空は「未指定」として扱う。
    def _int_env(name: str, default: int) -> int:
        v = os.environ.get(name, "").strip()
        return int(v) if v else default

    year = _int_env("CLIMATE_TARGET_YEAR", n.year)
    month = _int_env("CLIMATE_TARGET_MONTH", n.month)

    half = os.environ.get("CLIMATE_TARGET_HALF", "").strip().lower()
    if half not in ("first", "second"):
        half = "first" if n.day <= 15 else "second"

    if half == "first":
        start_day, end_day = 1, 15
    else:
        start_day = 16
        end_day = calendar.monthrange(year, month)[1]

    comparison_years = [year - 1, year - 2, year - 3]
    return year, month, start_day, end_day, comparison_years


def is_post_day() -> bool:
    """
    自動投稿日ゲート。
      ・CLIMATE_FORCE=1 または workflow_dispatch 相当なら常に実行。
      ・それ以外は JST の実行日が CLIMATE_POST_DAYS（既定 "1,16"）のときだけ実行。
    毎日 16:00 UTC(=翌01:00 JST) 起動でも、1日/16日だけ投稿できるようにするため。
    """
    if os.environ.get("CLIMATE_FORCE", "0").lower() in ("1", "true", "yes", "on"):
        return True
    days = {d.strip() for d in os.environ.get("CLIMATE_POST_DAYS", "1,16").split(",") if d.strip()}
    return str(now_jst().day) in days


# =============================================================================
# etrn 日別表の取得・解析
# =============================================================================
def _clean_value(raw: object) -> Optional[float]:
    """
    etrn セル文字列を数値に。
      "×" / "///" / "#"      → 欠測(None)
      "--"                   → 現象なし(0.0)  ※最深積雪の"降雪なし"等
      "8.5 )" / "8.5 ]" 等    → 記号を除いて 8.5
    """
    s = str(raw).strip()
    if s in ("", "nan", "None"):
        return None
    if s in ("×", "///", "#", "="):
        return None
    if s.startswith("--"):
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _col_join(col) -> str:
    if isinstance(col, tuple):
        return " ".join(str(c) for c in col)
    return str(col)


def _select_data_table(tables: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """気温の最高/最低を含む本体テーブルを選ぶ。"""
    best = None
    for t in tables:
        blob = " ".join(_col_join(c) for c in t.columns)
        if "最高" in blob and "最低" in blob:
            if best is None or t.shape[0] > best.shape[0]:
                best = t
    if best is None:
        # フォールバック: 最も行数の多い表
        best = max(tables, key=lambda t: t.shape[0]) if tables else None
    return best


def _find_col(df: pd.DataFrame, must_all: List[str]) -> Optional[object]:
    """列見出し（結合文字列）に must_all の全語を含む列を返す。"""
    for col in df.columns:
        blob = _col_join(col)
        if all(w in blob for w in must_all):
            return col
    return None


def fetch_station_month(prec_no: str, block_no: str, kind: str, year: int, month: int) -> Dict[str, Dict[int, float]]:
    """
    指定局・年月の日別表を取得し、{element: {day: value}} を返す。
    取得失敗時は空 dict。
    """
    view = "daily_s1" if kind == "s1" else "daily_a1"
    url = f"{ETRN_BASE}/{view}.php?prec_no={prec_no}&block_no={block_no}&year={year}&month={month}&day=&view="

    out: Dict[str, Dict[int, float]] = {"tmax": {}, "tmin": {}, "snow": {}}
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.encoding = "utf-8"
        if r.status_code != 200 or "ページを表示することが出来ませんでした" in r.text:
            print(f"[NG] etrn {view} block_no={block_no} {year}-{month:02d}: HTTP={r.status_code} URL={url}")
            return out

        tables = pd.read_html(io.StringIO(r.text))
        df = _select_data_table(tables)
        if df is None or df.empty:
            print(f"[NG] etrn table not found: block_no={block_no} {year}-{month:02d}")
            return out

        col_day = df.columns[0]
        col_tmax = _find_col(df, ["気温", "最高"]) or _find_col(df, ["最高"])
        col_tmin = _find_col(df, ["気温", "最低"]) or _find_col(df, ["最低"])
        col_snow = _find_col(df, ["最深積雪"])

        print(f"[INFO] cols block_no={block_no}: tmax={col_tmax} tmin={col_tmin} snow={col_snow}")

        for _, row in df.iterrows():
            day = _clean_value(row[col_day])
            if day is None:
                continue
            d = int(day)
            if not (1 <= d <= 31):
                continue
            if col_tmax is not None:
                v = _clean_value(row[col_tmax])
                if v is not None:
                    out["tmax"][d] = v
            if col_tmin is not None:
                v = _clean_value(row[col_tmin])
                if v is not None:
                    out["tmin"][d] = v
            if col_snow is not None:
                v = _clean_value(row[col_snow])
                if v is not None:
                    out["snow"][d] = v

        print(f"[OK] etrn {view} block_no={block_no} {year}-{month:02d}: "
              f"tmax={len(out['tmax'])} tmin={len(out['tmin'])} snow={len(out['snow'])}")
    except Exception as e:
        print(f"[ERR] fetch {view} block_no={block_no} {year}-{month:02d}: {e}")

    return out


def collect_data(
    month: int, comparison_years: List[int],
    stations: Optional[List[Tuple[str, str, str, str]]] = None,
) -> Dict[str, Dict[int, Dict[str, Dict[int, float]]]]:
    """
    data[station_name][year][element][day] = value
    横手のように block_no 未設定の局はスキップ（ログのみ）。
    stations を省略すると既定の STATIONS（秋田県3地点）を使う。
    """
    data: Dict[str, Dict[int, Dict[str, Dict[int, float]]]] = {}
    for name, prec_no, block_no, kind in (stations or STATIONS):
        data[name] = {}
        if not block_no:
            print(f"[SKIP] {name}: block_no 未設定のためスキップ（STATIONS に block_no を入れてください）")
            continue
        for y in comparison_years:
            data[name][y] = fetch_station_month(prec_no, block_no, kind, y, month)
            time.sleep(0.4)  # etrnへの連続アクセスを控えめに
    return data


# =============================================================================
# 作図
# =============================================================================
def _setup_japanese_font() -> None:
    candidates = [
        "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic",
        "TakaoGothic", "VL Gothic", "Hiragino Sans", "Yu Gothic",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            print(f"[INFO] font: {name}")
            break
    else:
        print("[WARN] 日本語フォント未検出。ラベルが□になる可能性があります（fonts-noto-cjk を入れてください）")
    plt.rcParams["axes.unicode_minus"] = False


def build_figure(
    data: Dict[str, Dict[int, Dict[str, Dict[int, float]]]],
    year: int, month: int, start_day: int, end_day: int,
    comparison_years: List[int],
    stations: Optional[List[Tuple[str, str, str, str]]] = None,
) -> bytes:
    """stations を省略すると既定の STATIONS（秋田県3地点）を使う。"""
    stations = stations or STATIONS
    _setup_japanese_font()

    days = list(range(start_day, end_day + 1))
    n_years = len(comparison_years)
    n_st = len(stations)

    elements = elements_for_month(month)  # 積雪は12〜3月のみ
    n_col = len(elements)

    # 気温は最高・最低で目盛りを完全に揃える（全地点の最高/最低をまとめて共通レンジに）。
    temp_vals = [
        v
        for (name, _p, _b, _k) in stations
        for y in comparison_years
        for ekey in ("tmax", "tmin")
        for v in data.get(name, {}).get(y, {}).get(ekey, {}).values()
        if v is not None
    ]
    if temp_vals:
        tlo = math.floor((min(temp_vals) - 1) / 5) * 5
        thi = math.ceil((max(temp_vals) + 1) / 5) * 5
    else:
        tlo, thi = 0, 35

    fig, axes = plt.subplots(n_st, n_col, figsize=(5.0 * n_col, 3.9 * n_st), squeeze=False)

    for r, (name, _p, _b, _k) in enumerate(stations):
        for c, (ekey, etitle) in enumerate(elements):
            ax = axes[r][c]
            st_years = data.get(name, {})

            has_any = any(st_years.get(y, {}).get(ekey) for y in comparison_years)

            if not has_any:
                ax.text(0.5, 0.5, "データなし", ha="center", va="center",
                        transform=ax.transAxes, color="#999", fontsize=12)
            elif ekey in ("tmax", "tmin"):
                for yi, y in enumerate(comparison_years):
                    series = st_years.get(y, {}).get(ekey, {})
                    ys = [series.get(d) for d in days]
                    ax.plot(days, ys, marker="o", ms=3, lw=1.6,
                            color=YEAR_COLORS[yi % len(YEAR_COLORS)], label=str(y))
                ax.axhline(0, color="#888", lw=0.8, zorder=0)  # 0℃線
                ax.set_ylim(tlo, thi)  # 最高・最低で目盛りを揃える
            else:  # snow: 年ごとの棒グラフ（平年線なし）
                width = 0.8 / max(1, n_years)
                for yi, y in enumerate(comparison_years):
                    series = st_years.get(y, {}).get(ekey, {})
                    ys = [series.get(d, 0.0) or 0.0 for d in days]
                    xs = [d + (yi - (n_years - 1) / 2) * width for d in days]
                    ax.bar(xs, ys, width=width,
                           color=YEAR_COLORS[yi % len(YEAR_COLORS)], label=str(y))

            if r == 0:
                ax.set_title(etitle, fontsize=11)
            if c == 0:
                # 地名は「●／1文字ずつ縦積み」で表示する（例: ●\n鷹\n巣）。
                vlabel = "●\n" + "\n".join(name)
                ax.set_ylabel(vlabel, rotation=0, ha="center", va="center",
                              labelpad=18, fontsize=12, linespacing=1.2)
            ax.grid(True, axis="y", alpha=0.3)
            ax.set_xlim(start_day - 0.6, end_day + 0.6)
            ax.set_xticks(days)
            ax.tick_params(labelsize=8)

    elem_names = {"tmax": "最高気温", "tmin": "最低気温", "snow": "最深積雪"}
    subtitle_elems = "・".join(elem_names[k] for k, _t in elements)
    fig.suptitle(
        f"過去3年比較 {month}/{start_day}〜{month}/{end_day}"
        f"（{comparison_years[0]}・{comparison_years[1]}・{comparison_years[2]}）"
        f" ／ {subtitle_elems}",
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])

    # 凡例（タイトルの下・グラフの上に右寄せ。タイトルと重ならないよう
    # bbox_to_anchorで明示的に少し下げた位置に固定する）
    handles = [plt.Line2D([0], [0], color=YEAR_COLORS[i % len(YEAR_COLORS)], lw=3)
               for i in range(n_years)]
    labels = [str(y) for y in comparison_years]
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.99, 0.965),
               ncol=n_years, frameon=False, fontsize=10)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    return buf.getvalue()


# =============================================================================
# R2 / Discord
# =============================================================================
def upload_r2(key: str, blob: bytes) -> str:
    if not R2_ENABLE:
        return ""
    try:
        from module.utils.r2_utils import put_bytes, make_url
        put_bytes(key, blob, content_type="image/png")
        url = make_url(key)
        print(f"[OK] R2: {url}")
        return url
    except Exception as e:
        print(f"[WARN] R2 upload failed: {e}")
        return ""


def post_discord(png: bytes, title: str, r2_url: str = "") -> None:
    url = discord_webhook_url()
    if not (DISCORD_ENABLE and url):
        print("[INFO] Discord 無効（DISCORD_ENABLE / webhook 未設定）")
        return

    content = title
    if r2_url:
        retention = os.environ.get("R2_RETENTION_DAYS", "30")
        content += f"\n📥 [気温 高解像度PNGをダウンロード（{retention}日間有効）](<{r2_url}>)"

    import json
    payload = {"content": content[:1900], "allowed_mentions": {"parse": []}, "flags": 4}
    try:
        r = requests.post(
            url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files={"file": ("climate_3yr.png", io.BytesIO(png), "image/png")},
            timeout=120,
        )
        r.raise_for_status()
        print("[OK] Discord posted")
    except Exception as e:
        print(f"[ERR] Discord post failed: {e}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start Climate 3yr ===")

    if not is_post_day():
        print(f"[INFO] 投稿日ではないためスキップ（JST {now_jst():%Y-%m-%d %H:%M}）。"
              f" 強制実行は CLIMATE_FORCE=1")
        print("=== Skip ===")
        return

    year, month, start_day, end_day, comparison_years = resolve_window()
    print(f"[INFO] target={year}-{month:02d} {start_day}〜{end_day} / years={comparison_years}")

    data = collect_data(month, comparison_years)
    png = build_figure(data, year, month, start_day, end_day, comparison_years)

    half_label = "前半" if start_day == 1 else "後半"
    day_jst = now_jst().strftime("%Y%m%d")
    key = f"{year}{month:02d}/climate_{half_label}_{start_day:02d}-{end_day:02d}.png"
    r2_url = upload_r2(key, png)

    elem_names = {"tmax": "最高気温", "tmin": "最低気温", "snow": "最深積雪"}
    elem_label = "・".join(elem_names[k] for k, _t in elements_for_month(month))
    title = (f"📊 過去3年 気象比較（鷹巣・秋田・横手）\n"
             f"{month}月{half_label}（{month}/{start_day}〜{month}/{end_day}）"
             f"／{elem_label}")
    post_discord(png, title, r2_url)

    # SNS投稿は climate_akita.py（統合エントリ）で2枚まとめて行う。
    # この単体実行では Discord のみ（画像確認・デバッグ用）。

    print("=== Done ===")


if __name__ == "__main__":
    main()
