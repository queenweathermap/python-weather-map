# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# JMA AMeDAS データ → Discord(#amedas) 配信
# urllib stdlib のみ・認証不要・Playwright不使用
#
# 配信: 朝3時 / 午後3時（JST）
# 出力:
#   [1] 秋田県 各局一覧（気温・降水・風速・積雪）
#   [2] 全国ランキング（気温高低 / 24h降水 / 最大風速 / 積雪深）
# =============================================================================

from __future__ import annotations

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

# 秋田県のバウンディングボックス（度）
# AMeDASのコード体系は非公開のため、座標で確実にフィルタする
AKITA_LAT = (38.8, 40.6)
AKITA_LON = (139.4, 141.2)

RANK_TOP_N = int(os.environ.get("AMEDAS_RANK_TOP_N", "10"))

JST = timezone(timedelta(hours=9))

WIND_DIR = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]

# =============================================================================
# HTTP
# =============================================================================

def _fetch(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)"},
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
    """[value, quality] 形式から値を取り出す。"""
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
    """正時の14桁 UTC タイムスタンプ一覧（新→古）。"""
    cur = base_utc.replace(minute=0, second=0, microsecond=0)
    result = []
    for _ in range(hours):
        result.append(cur.strftime("%Y%m%d%H%M%S"))
        cur -= timedelta(hours=1)
    return result


# =============================================================================
# 地点テーブル
# =============================================================================

def _latlon(info: dict) -> Optional[Tuple[float, float]]:
    """amedastable の lat/lon を 10進度 (lat, lon) に変換する。
    フォーマットは [度, 分] または [度, 分, 秒] の配列。"""
    lat_raw = info.get("lat")
    lon_raw = info.get("lon")
    if not (lat_raw and lon_raw and len(lat_raw) >= 2 and len(lon_raw) >= 2):
        return None
    try:
        lat = float(lat_raw[0]) + float(lat_raw[1]) / 60
        if len(lat_raw) >= 3:
            lat += float(lat_raw[2]) / 3600
        lon = float(lon_raw[0]) + float(lon_raw[1]) / 60
        if len(lon_raw) >= 3:
            lon += float(lon_raw[2]) / 3600
        return lat, lon
    except (TypeError, ValueError):
        return None


def _load_akita_stations(table: dict) -> Dict[str, str]:
    """座標で秋田県局を抽出 → {code: 漢字名}。"""
    result = {}
    for code, info in table.items():
        ll = _latlon(info)
        if ll:
            lat, lon = ll
            if AKITA_LAT[0] <= lat <= AKITA_LAT[1] and AKITA_LON[0] <= lon <= AKITA_LON[1]:
                result[code] = info.get("kjName", code)
    print(f"[INFO] 秋田県局: {len(result)} stations")
    if result:
        sample = list(result.items())[:5]
        print(f"[INFO] 秋田県局サンプル: {sample}")
    else:
        # デバッグ: テーブルの先頭3局の座標を出力
        for code, info in list(table.items())[:3]:
            print(f"[DEBUG] station {code}: kjName={info.get('kjName')}, lat={info.get('lat')}, lon={info.get('lon')}")
    return dict(sorted(result.items()))


# =============================================================================
# データ集計（秋田県）
# =============================================================================

def _collect(
    akita: Dict[str, str],
    ts_list: List[str],
    jst_today_start_utc: datetime,
) -> List[dict]:
    """各局の気温・降水・風速・積雪データを集計して返す。"""
    maps: Dict[str, dict] = {}
    for ts in ts_list:
        data = _fetch(f"{MAP_BASE_URL}/{ts}.json")
        if data:
            maps[ts] = data
    print(f"[INFO] maps fetched: {len(maps)}/{len(ts_list)}")

    results = []
    for code, name in akita.items():
        latest_entry = maps.get(ts_list[0], {}).get(code, {}) if ts_list else {}

        temp     = _val(latest_entry, "temp")
        wind     = _val(latest_entry, "wind")
        snow     = _val(latest_entry, "snow")
        wind_dir = _val(latest_entry, "windDirection")

        daily_temps: List[float] = []
        rn_by_ts: List[Tuple[datetime, float]] = []

        for ts_str, map_data in maps.items():
            ts_utc = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            entry = map_data.get(code, {})
            t_val  = _val(entry, "temp")
            rn_val = _val(entry, "rn")
            if t_val is not None and ts_utc >= jst_today_start_utc:
                daily_temps.append(t_val)
            if rn_val is not None:
                rn_by_ts.append((ts_utc, rn_val))

        max_temp = max(daily_temps) if daily_temps else None
        min_temp = min(daily_temps) if daily_temps else None

        rn_sorted = sorted(rn_by_ts, key=lambda x: x[0], reverse=True)
        rn1h  = rn_sorted[0][1]  if len(rn_sorted) >= 1 else 0.0
        rn3h  = sum(v for _, v in rn_sorted[:3])
        rn24h = sum(v for _, v in rn_sorted[:24])

        results.append({
            "code": code,
            "name": name,
            "temp": temp,
            "max_temp": max_temp,
            "min_temp": min_temp,
            "wind": wind,
            "wind_dir": int(wind_dir) if wind_dir is not None else None,
            "snow": snow,
            "rn1h":  rn1h,
            "rn3h":  rn3h,
            "rn24h": rn24h,
        })

    return results


# =============================================================================
# 全国ランキング
# =============================================================================

def _accum_maps(ts_list: List[str], n: int) -> Dict[str, float]:
    """全局の n 時間積算降水量 {code: mm} を返す。"""
    totals: Dict[str, float] = {}
    for ts in ts_list[:n]:
        data = _fetch(f"{MAP_BASE_URL}/{ts}.json") or {}
        for code, obs in data.items():
            v = _val(obs, "rn")
            if v is not None:
                totals[code] = totals.get(code, 0.0) + v
    return totals


def _ranking(latest_ts: str, ts_list: List[str], table: dict):
    data = _fetch(f"{MAP_BASE_URL}/{latest_ts}.json") or {}

    temps, winds, snows = [], [], []
    for code, obs in data.items():
        nm = table.get(code, {}).get("kjName", code) if isinstance(table.get(code), dict) else code
        t = _val(obs, "temp")
        w = _val(obs, "wind")
        s = _val(obs, "snow")
        if t is not None:
            temps.append((code, nm, t))
        if w is not None:
            winds.append((code, nm, w))
        if s is not None and s > 0:
            snows.append((code, nm, s))

    hot  = sorted(temps, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    cold = sorted(temps, key=lambda x: x[2])[:RANK_TOP_N]
    top_wind = sorted(winds, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    top_snow = sorted(snows, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]

    # 24h 積算降水（既にmapを取得済みのデータを使い回すため別途集計）
    rn24 = _accum_maps(ts_list, 24)
    top_rn = []
    for code, total in sorted(rn24.items(), key=lambda x: x[1], reverse=True):
        if total > 0 and code in table:
            nm = table[code].get("kjName", code) if isinstance(table[code], dict) else code
            top_rn.append((code, nm, total))
    top_rn = top_rn[:RANK_TOP_N]

    return hot, cold, top_wind, top_snow, top_rn


# =============================================================================
# フォーマット
# =============================================================================

def _tf(v: Optional[float]) -> str:
    return f"{v:5.1f}" if v is not None else "  ---"


def _rf(v: float) -> str:
    return f"{v:5.1f}" if v > 0 else "  0.0"


def _wf(wind: Optional[float], wd: Optional[int]) -> str:
    if wind is None:
        return " ---"
    s = f"{wind:4.1f}"
    if wd and 1 <= wd <= 16:
        s += WIND_DIR[wd - 1]
    return s


def _sf(snow: Optional[float]) -> str:
    if snow is None or snow <= 0:
        return " ---"
    return f"{snow:4.0f}cm"


def _fmt_akita(results: List[dict], jst_now: datetime) -> str:
    ts = jst_now.strftime("%m/%d %H:%M")
    lines = [
        f"🌡️ **アメダス 秋田県**　{ts} JST",
        "```",
        "地点    気温  最高  最低  風(m/s) 積雪  1h雨  24h雨",
        "─" * 52,
    ]
    for r in results:
        wd = _wf(r["wind"], r["wind_dir"])
        lines.append(
            f"{r['name'][:5]:<6}"
            f"{_tf(r['temp'])} "
            f"{_tf(r['max_temp'])} "
            f"{_tf(r['min_temp'])} "
            f"{wd:>7} "
            f"{_sf(r['snow']):>5}  "
            f"{_rf(r['rn1h'])} "
            f"{_rf(r['rn24h'])}"
        )
    if not results:
        lines.append("（秋田県局データなし）")
    lines.append("```")
    return "\n".join(lines)


def _fmt_ranking(
    hot, cold, top_wind, top_snow, top_rn, jst_now: datetime
) -> str:
    ts = jst_now.strftime("%m/%d %H:%M")
    col = "{:>2}. {:<9} {:>6}"
    lines = [f"🏆 **全国ランキング**　{ts} JST", ""]

    def section(title: str, items: list, unit: str) -> List[str]:
        out = [f"**{title}**", "```"]
        for i, (_, name, v) in enumerate(items, 1):
            out.append(col.format(i, name[:9], f"{v:.1f}{unit}"))
        out.append("```")
        return out

    lines += section(f"🔥 最高気温 TOP{RANK_TOP_N}", hot,  "℃")
    lines.append("")
    lines += section(f"🥶 最低気温 TOP{RANK_TOP_N}", cold, "℃")

    if top_rn:
        lines.append("")
        lines += section(f"💧 24h降水量 TOP{RANK_TOP_N}", top_rn, "mm")

    if top_wind:
        lines.append("")
        lines += section(f"💨 最大風速 TOP{RANK_TOP_N}", top_wind, "m/s")

    if top_snow:
        lines.append("")
        lines += section(f"❄️ 積雪深 TOP{RANK_TOP_N}", top_snow, "cm")

    return "\n".join(lines)


# =============================================================================
# Discord 送信
# =============================================================================

def _post(content: str):
    if not DISCORD_AMEDAS_WEBHOOK_URL:
        print("[SKIP] DISCORD_AMEDAS_WEBHOOK_URL not set")
        return
    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_AMEDAS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "akita-amedas-bot/1.0 (+https://github.com/)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"[OK] Discord HTTP {r.status}")
    except Exception as e:
        print(f"[ERR] Discord post: {e}")


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Amedas ===")

    jst_now, latest_utc = _parse_latest()
    latest_ts = latest_utc.strftime("%Y%m%d%H%M%S")
    print(f"[INFO] latest: {jst_now.strftime('%Y-%m-%d %H:%M JST')} ({latest_ts})")

    # 地点テーブル
    table = _fetch(AMEDAS_TABLE_URL) or {}
    akita = _load_akita_stations(table)

    # 過去24時間の正時タイムスタンプ（新→古）
    ts_list = _hourly_ts_list(latest_utc, 24)

    # JST 当日 0時の UTC
    jst_today_start_utc = jst_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    # 秋田データ集計
    results = _collect(akita, ts_list, jst_today_start_utc)

    # 全国ランキング
    hot, cold, top_wind, top_snow, top_rn = _ranking(latest_ts, ts_list, table)

    # Discord 配信
    _post(_fmt_akita(results, jst_now))
    _post(_fmt_ranking(hot, cold, top_wind, top_snow, top_rn, jst_now))

    print("=== Done ===")


if __name__ == "__main__":
    main()
