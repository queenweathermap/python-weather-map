# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/daylength.py
#
# 秋田県「昼の長さ / 日の出・日の入り」インフォグラフィック
#
#   ・climate_3yr と同じチャンネル・同じタイミング（1日/16日 01:00 JST, 前半/後半）で
#     もう1枚として投稿する。
#   ・天文計算(astral)で 日の出/日の入り/昼の長さ を算出（API不要・再現性あり）。
#   ・日付ごとの24時間クロック円（昼=黄/夜=灰）＋時刻＋前日比、
#     日本地図（秋田強調）、冬至/夏至の注記、反対側の至の参照円を描く。
#
# 期間・投稿日ゲート・Discord/R2 は climate_3yr の関数を再利用する。
# =============================================================================

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Wedge

from astral import LocationInfo
from astral.sun import sun

from module.jobs.climate_3yr import (
    resolve_window,
    is_post_day,
    now_jst,
    upload_r2,
    discord_webhook_url,
    _setup_japanese_font,
)

# =============================================================================
# 設定
# =============================================================================
AKITA_LAT = 39.7186
AKITA_LON = 140.1024
TZ = ZoneInfo("Asia/Tokyo")
OBS = LocationInfo("Akita", "Japan", "Asia/Tokyo", AKITA_LAT, AKITA_LON).observer

GEOJSON_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "japan_prefectures.geojson")

DAY_COLOR = "#f0b429"    # 昼（黄）
NIGHT_COLOR = "#4a4a4a"  # 夜（灰）
SUNRISE_COLOR = "#e08a00"
SUNSET_COLOR = "#c0561f"

COLS = 5
ROW_H = 1.42

DISCORD_ENABLE = os.environ.get("DISCORD_ENABLE", "1").lower() in ("1", "true", "yes", "on")


# =============================================================================
# 天文計算
# =============================================================================
def day_info(d: date, observer=OBS):
    """指定日の (日の出dt, 日の入りdt, 昼の長さtimedelta) を返す。observer省略時は秋田。"""
    s = sun(observer, date=d, tzinfo=TZ)
    sr, ss = s["sunrise"], s["sunset"]
    return sr, ss, (ss - sr)


def _hours(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _daylen_str(seconds: float) -> str:
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}h {m}m {s}s"


def _ampm(dt: datetime) -> str:
    # "06:57:02 AM" 形式
    return dt.strftime("%I:%M:%S %p")


# =============================================================================
# 描画パーツ
# =============================================================================
def _ang(h: float) -> float:
    """24時間クロック（0時=上, 6時=右, 12時=下, 18時=左）の角度[deg]。"""
    return 90.0 - (h / 24.0) * 360.0


def draw_clock(ax, cx, cy, r, sr_h, ss_h, *, daylen_str=None, daylen_fs=6.0, ticks=True):
    """クロック円: 夜=灰の全円 + 昼=黄のwedge（日の出→正午→日の入り）。"""
    ax.add_patch(Circle((cx, cy), r, facecolor=NIGHT_COLOR, edgecolor="none", zorder=1))
    ax.add_patch(Wedge((cx, cy), r, _ang(ss_h), _ang(sr_h),
                       facecolor=DAY_COLOR, edgecolor="none", zorder=2))
    if ticks:
        off = r + r * 0.20
        common = dict(ha="center", va="center", fontsize=r * 18, color="#999", zorder=3)
        ax.text(cx, cy + off, "0", **common)
        ax.text(cx + off, cy, "6", **common)
        ax.text(cx, cy - off, "12", **common)
        ax.text(cx - off, cy, "18", **common)
    if daylen_str:
        ax.text(cx, cy - r * 0.42, daylen_str, ha="center", va="center",
                fontsize=daylen_fs, color="#333", zorder=4)


def draw_map(ax, highlight_pref: str = "秋田県", *, xlim=(128, 146), ylim=(30, 46)):
    """
    日本地図（highlight_pref を強調。省略時は秋田県）。GeoJSON が無ければ静かにスキップ。
    xlim/ylim: 既定は本州〜九州が収まる範囲。沖縄県のように範囲外の地域を
    強調する場合は、その地域が収まる範囲を明示的に渡す。
    """
    if not os.path.exists(GEOJSON_PATH):
        print(f"[WARN] geojson 無し: {GEOJSON_PATH}（地図スキップ）")
        ax.axis("off")
        return
    try:
        d = json.load(open(GEOJSON_PATH, encoding="utf-8"))
        for ft in d["features"]:
            akita = ft["properties"].get("nam_ja") == highlight_pref
            fc = "#4fae5a" if akita else "#ececec"
            geom = ft["geometry"]
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            for poly in polys:
                outer = poly[0]
                xs = [p[0] for p in outer]
                ys = [p[1] for p in outer]
                ax.fill(xs, ys, facecolor=fc, edgecolor="#a5a5a5", linewidth=0.3,
                        zorder=(3 if akita else 1))
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect(1.0 / math.cos(math.radians(38)))  # 緯度補正
    except Exception as e:
        print(f"[WARN] 地図描画失敗: {e}")
    ax.axis("off")


# =============================================================================
# 図の組み立て
# =============================================================================
def build_figure(
    year: int, month: int, start_day: int, end_day: int,
    *, city_label: str = "秋田県", observer=OBS, highlight_pref: str = "秋田県",
    map_xlim=(128, 146), map_ylim=(30, 46),
) -> bytes:
    """
    city_label/observer/highlight_pref を省略すると従来通り秋田県版になる。
    map_xlim/map_ylim: 地図の表示範囲。沖縄県など既定範囲(本州〜九州)に
    収まらない地域を強調する場合に指定する。
    """
    _setup_japanese_font()

    days = [date(year, month, d) for d in range(start_day, end_day + 1)]
    info = {d: day_info(d, observer) for d in days}
    prev = days[0] - timedelta(days=1)
    prev_len = day_info(prev, observer)[2].total_seconds()

    n = len(days)
    rows = math.ceil(n / COLS)

    # 反対側の至（コントラスト参照）
    avg_len = sum(info[d][2].total_seconds() for d in days) / max(1, n)
    if avg_len < 12 * 3600:
        ref_date, ref_label = date(year, 6, 21), "夏至の頃"
    else:
        ref_date, ref_label = date(year, 12, 21), "冬至の頃"
    ref_sr, ref_ss, ref_len = day_info(ref_date, observer)

    # 期間内の至（冬至/夏至）
    sol_day = 22 if month == 12 else (21 if month == 6 else None)
    sol_mark = None  # (day, 見出し, 補足)
    if sol_day and start_day <= sol_day <= end_day:
        sol_mark = (sol_day, "冬至" if month == 12 else "夏至",
                    "最も昼が短い" if month == 12 else "最も昼が長い")

    fig = plt.figure(figsize=(12.6, max(4.6, 2.0 + rows * 1.9)))

    ax_cards = fig.add_axes([0.02, 0.02, 0.75, 0.90])
    ax_cards.set_xlim(-0.05, COLS + 0.05)
    ax_cards.set_ylim(-0.15, rows * ROW_H + 0.1)
    ax_cards.set_aspect("equal")
    ax_cards.axis("off")

    r = 0.30
    for i, d in enumerate(days):
        col = i % COLS
        row = i // COLS
        cx = col + 0.5
        yt = (rows - row) * ROW_H  # セル上端（y上向き）

        sr, ss, dl = info[d]
        dl_s = dl.total_seconds()
        delta = dl_s - prev_len
        prev_len = dl_s

        # 日付見出し
        ax_cards.text(cx, yt - 0.13, f"{d.month}/{d.day}", ha="center", va="center",
                      fontsize=13, fontweight="bold", color="#222")

        # 至の注記
        if sol_mark and d.day == sol_mark[0]:
            ax_cards.text(cx, yt - 0.30, f"{sol_mark[1]}・{sol_mark[2]}", ha="center", va="center",
                          fontsize=6.5, color="#d0322f", fontweight="bold")

        # クロック
        clock_cy = yt - 0.60
        draw_clock(ax_cards, cx, clock_cy, r, _hours(sr), _hours(ss),
                   daylen_str=_daylen_str(dl_s), daylen_fs=6.0)

        # 日の出 / 日の入り
        ax_cards.text(cx, yt - 1.06, f"↑ {_ampm(sr)}", ha="center", va="center",
                      fontsize=7, color=SUNRISE_COLOR)
        ax_cards.text(cx, yt - 1.20, f"↓ {_ampm(ss)}", ha="center", va="center",
                      fontsize=7, color=SUNSET_COLOR)

        # 前日比（±秒）
        sign = "+" if delta >= 0 else "−"
        ax_cards.text(cx, yt - 1.33, f"前日比 {sign}{abs(int(round(delta)))}s",
                      ha="center", va="center", fontsize=5.6, color="#888")

    # 右上: 日本地図
    ax_map = fig.add_axes([0.775, 0.50, 0.215, 0.45])
    draw_map(ax_map, highlight_pref, xlim=map_xlim, ylim=map_ylim)

    # 右下: 反対側の至の参照円
    ax_ref = fig.add_axes([0.775, 0.06, 0.215, 0.40])
    ax_ref.set_xlim(-1, 1)
    ax_ref.set_ylim(-1.5, 1.15)
    ax_ref.set_aspect("equal")
    ax_ref.axis("off")
    draw_clock(ax_ref, 0.0, 0.30, 0.62, _hours(ref_sr), _hours(ref_ss),
               daylen_str=None, ticks=True)
    ax_ref.text(0.0, -0.65, ref_label, ha="center", va="center", fontsize=11, color="#555")
    ax_ref.text(0.0, -1.02, _daylen_str(ref_len.total_seconds()), ha="center", va="center",
                fontsize=10, color="#333")

    # タイトル
    half = "前半" if start_day == 1 else "後半"
    fig.text(0.02, 0.965, f"{city_label} 昼の長さ ／ 日の出・日の入り", fontsize=15, fontweight="bold")
    fig.text(0.02, 0.935, f"{month}月{half}（{month}/{start_day}〜{month}/{end_day}）",
             fontsize=10, color="#555")

    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


# =============================================================================
# Discord
# =============================================================================
def post_discord(png: bytes, title: str, r2_url: str = "") -> None:
    url = discord_webhook_url()
    if not (DISCORD_ENABLE and url):
        print("[INFO] Discord 無効（daylength）")
        return
    content = title
    if r2_url:
        content += f"\n**[★高解像度PNGを表示](<{r2_url}>)**"
    import io
    payload = {"content": content[:1900], "allowed_mentions": {"parse": []}, "flags": 4}
    try:
        r = requests.post(
            url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files={"file": ("daylength.png", io.BytesIO(png), "image/png")},
            timeout=120,
        )
        r.raise_for_status()
        print("[OK] Discord posted (daylength)")
    except Exception as e:
        print(f"[ERR] Discord post failed (daylength): {e}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start Daylength ===")

    if not is_post_day():
        print(f"[INFO] 投稿日ではないためスキップ（daylength / JST {now_jst():%Y-%m-%d %H:%M}）")
        print("=== Skip ===")
        return

    year, month, start_day, end_day, _years = resolve_window()
    print(f"[INFO] daylength target={year}-{month:02d} {start_day}〜{end_day}")

    png = build_figure(year, month, start_day, end_day)

    half = "前半" if start_day == 1 else "後半"
    key = f"{year}{month:02d}/daylength_{half}_{start_day:02d}-{end_day:02d}.png"
    r2_url = upload_r2(key, png)

    title = (f"🌅 秋田県 昼の長さ（日の出・日の入り）\n"
             f"{month}月{half}（{month}/{start_day}〜{month}/{end_day}）")
    post_discord(png, title, r2_url)

    # SNS投稿は climate_akita.py（統合エントリ）で2枚まとめて行う。
    # この単体実行では Discord のみ（画像確認・デバッグ用）。

    print("=== Done ===")


if __name__ == "__main__":
    main()
