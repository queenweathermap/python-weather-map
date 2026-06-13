# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# JMA AMeDAS データ → Discord(#amedas) 配信
# urllib stdlib のみ・認証不要・Playwright不使用
#
# 配信: 朝3時 / 午後3時（JST）
# 出力:
#   [1] 秋田県 各局一覧（気温・風速・積雪・1h/24h降水）
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

# JMA AMeDAS コードは 2 桁プレフィックスが都道府県に対応
#   31=青森  32=秋田  33=岩手  ...
# lat/lon バウンディングボックスは隣県を混入させるため使わない
AKITA_CODE_PREFIX = "32"

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
    """[value, quality] 形式から値を取り出す。quality 0/1 = valid。"""
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

def _load_akita_stations(table: dict) -> Dict[str, str]:
    """秋田県 AMeDAS 局（コード 32xxx かつ気温観測局）→ {code: 漢字名}。"""
    result = {}
    for code, info in table.items():
        if not code.startswith(AKITA_CODE_PREFIX):
            continue
        elems = info.get("elems", "")
        if not elems or elems[0] != "1":   # elems[0]='1' が気温観測あり
            continue
        result[code] = info.get("kjName", code)
    print(f"[INFO] 秋田県局（気温あり）: {len(result)} stations")
    return dict(sorted(result.items()))


# =============================================================================
# マップ一括取得（再利用）
# =============================================================================

def _fetch_maps(ts_list: List[str]) -> Dict[str, dict]:
    """各時刻の全局観測マップを取得する（一度だけ呼ぶ）。"""
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
        rn1h  = rn_sorted[0][1]  if len(rn_sorted) >= 1 else 0.0
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
            "humidity": humidity,
            "rn1h":  rn1h,
            "rn24h": rn24h,
        })

    return results


# =============================================================================
# 全国ランキング
# =============================================================================

def _ranking(maps: Dict[str, dict], ts_list: List[str], table: dict):
    """既取得の maps を再利用し、全国ランキングを算出する。
    最新の正時マップ（ts_list[0]）を基準にランキングを算出する。
    """
    latest_map = maps.get(ts_list[0], {}) if ts_list else {}

    def name_of(code: str) -> str:
        v = table.get(code)
        if isinstance(v, dict):
            return v.get("kjName", code)
        return code

    temps, winds, snows, hums = [], [], [], []
    for code, obs in latest_map.items():
        nm = name_of(code)
        t = _val(obs, "temp")
        w = _val(obs, "wind")
        s = _val(obs, "snow")
        h = _val(obs, "humidity")
        if t is not None:
            temps.append((code, nm, t))
        if w is not None:
            winds.append((code, nm, w))
        if s is not None and s > 0:
            snows.append((code, nm, s))
        if h is not None:
            hums.append((code, nm, h))

    hot      = sorted(temps, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    cold     = sorted(temps, key=lambda x: x[2])[:RANK_TOP_N]
    top_wind = sorted(winds, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    top_snow = sorted(snows, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    top_dry  = sorted(hums,  key=lambda x: x[2])[:RANK_TOP_N]   # 湿度低い順

    # 24h 積算降水（共有 maps から集計）
    rn_totals: Dict[str, float] = {}
    for ts_str in ts_list[:24]:
        for code, obs in maps.get(ts_str, {}).items():
            v = _val(obs, "rn")
            if v is not None:
                rn_totals[code] = rn_totals.get(code, 0.0) + v

    top_rn = []
    for code, total in sorted(rn_totals.items(), key=lambda x: x[1], reverse=True):
        if total > 0 and isinstance(table.get(code), dict):
            top_rn.append((code, name_of(code), total))
    top_rn = top_rn[:RANK_TOP_N]

    return hot, cold, top_wind, top_snow, top_rn, top_dry


# =============================================================================
# フォーマット
# =============================================================================

def _tf(v: Optional[float]) -> str:
    return f"{v:5.1f}" if v is not None else "  ---"


def _rf(v: float) -> str:
    return f"{v:5.1f}" if v > 0 else "  0.0"


def _wf(wind: Optional[float], wd: Optional[int]) -> str:
    if wind is None:
        return "  ---"
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
        "地点    気温  最高  最低  風速      積雪  湿度  1h  24h",
        "─" * 52,
    ]
    for r in results:
        wd  = _wf(r["wind"], r["wind_dir"])
        hum = f"{r['humidity']:3.0f}%" if r["humidity"] is not None else " ---"
        lines.append(
            f"{r['name'][:4]:<5}"
            f"{_tf(r['temp'])} "
            f"{_tf(r['max_temp'])} "
            f"{_tf(r['min_temp'])} "
            f"{wd:<9}"
            f"{_sf(r['snow']):>5}"
            f"  {hum}"
            f"  {_rf(r['rn1h'])}"
            f"  {_rf(r['rn24h'])}"
        )
    if not results:
        lines.append("（秋田県局データなし）")
    lines.append("```")
    return "\n".join(lines)


def _fmt_ranking(
    hot, cold, top_wind, top_snow, top_rn, top_dry, jst_now: datetime
) -> str:
    ts = jst_now.strftime("%m/%d %H:%M")
    col = "{:>2}. {:<10} {:>7}"
    lines = [f"🏆 **全国ランキング**　{ts} JST", ""]

    def section(title: str, items: list, unit: str) -> List[str]:
        out = [f"**{title}**", "```"]
        for i, (_, name, v) in enumerate(items, 1):
            out.append(col.format(i, name[:10], f"{v:.1f}{unit}"))
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

    if top_dry:
        lines.append("")
        lines += section(f"🌵 最小湿度 TOP{RANK_TOP_N}", top_dry, "%")

    return "\n".join(lines)


# =============================================================================
# Discord 送信
# =============================================================================

def _post(content: str):
    if not DISCORD_AMEDAS_WEBHOOK_URL:
        print(f"[SKIP] DISCORD_AMEDAS_WEBHOOK_URL not set ({len(content)} chars)")
        return
    if len(content) > 2000:
        print(f"[WARN] message {len(content)} chars > 2000, Discord will reject")
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
    print(f"[INFO] latest obs: {jst_now.strftime('%Y-%m-%d %H:%M JST')}")

    table = _fetch(AMEDAS_TABLE_URL) or {}
    akita = _load_akita_stations(table)

    ts_list = _hourly_ts_list(latest_utc, 24)

    jst_today_start_utc = jst_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    # 24時間分のマップを一度だけ取得して両方の関数で共有
    maps = _fetch_maps(ts_list)

    results = _collect(akita, maps, ts_list, jst_today_start_utc)
    hot, cold, top_wind, top_snow, top_rn, top_dry = _ranking(maps, ts_list, table)

    msg1 = _fmt_akita(results, jst_now)
    msg2 = _fmt_ranking(hot, cold, top_wind, top_snow, top_rn, top_dry, jst_now)

    print(f"[INFO] msg1={len(msg1)} chars, msg2={len(msg2)} chars")

    _post(msg1)
    _post(msg2)

    print("=== Done ===")


if __name__ == "__main__":
    main()
