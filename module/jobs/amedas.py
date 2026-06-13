# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# JMA AMeDAS 秋田県データ → Discord(#amedas) 配信
# urllib stdlib のみ・認証不要・Playwright不使用
#
# 配信: 朝3時 / 午後3時（JST）
# データ:
#   ・秋田県各局: 現在気温 / 日最高 / 日最低 / 3h積算降水 / 24h積算降水
#   ・全国最高気温ランキング TOP10
#   ・全国最低気温ランキング TOP10
# =============================================================================

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional, Tuple

# =============================================================================
# JMA AMeDAS 公開API（認証不要）
# =============================================================================
LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.json"
AMEDAS_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
MAP_BASE_URL = "https://www.jma.go.jp/bosai/amedas/data/map"

DISCORD_AMEDAS_WEBHOOK_URL = os.environ.get("DISCORD_AMEDAS_WEBHOOK_URL", "")

# 秋田県 AMeDAS局コードのプレフィックス
AKITA_PREFIX = os.environ.get("AMEDAS_AKITA_PREFIX", "32")

# 秋田のバウンディングボックス（コード判定の補完）
AKITA_LAT = (38.8, 40.6)
AKITA_LON = (139.5, 141.2)

RANK_TOP_N = int(os.environ.get("AMEDAS_RANK_TOP_N", "10"))

JST = timezone(timedelta(hours=9))

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
        if e.code == 404:
            return None
        print(f"[WARN] HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"[WARN] fetch: {e} ({url})")
        return None


def _val(entry: dict, key: str) -> Optional[float]:
    """[value, quality] 形式から値を取り出す。品質コード 0/1 のみ採用。"""
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
    """latest_time.json を読んで (jst_now, latest_utc) を返す。"""
    raw = _fetch(LATEST_TIME_URL)
    if raw:
        utc = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    else:
        utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        utc = utc.replace(minute=(utc.minute // 10) * 10) - timedelta(minutes=10)
    return utc.astimezone(JST), utc


def _hourly_ts_list(base_utc: datetime, hours: int) -> List[str]:
    """base_utc の正時から hours 時間分の 14桁 UTC タイムスタンプ（新→古）。"""
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
    """コードプレフィックス or lat/lon で秋田県局を抽出 → {code: 漢字名}。"""
    result = {}
    for code, info in table.items():
        name = info.get("kjName", code)
        if code.startswith(AKITA_PREFIX):
            result[code] = name
            continue
        lat_raw = info.get("lat")
        lon_raw = info.get("lon")
        if lat_raw and lon_raw:
            try:
                lat = lat_raw[0] + lat_raw[1] / 60
                lon = lon_raw[0] + lon_raw[1] / 60
                if AKITA_LAT[0] <= lat <= AKITA_LAT[1] and AKITA_LON[0] <= lon <= AKITA_LON[1]:
                    result[code] = name
            except Exception:
                pass
    return dict(sorted(result.items()))


# =============================================================================
# データ集計
# =============================================================================

def _collect(
    akita: Dict[str, str],
    ts_list: List[str],
    jst_today_start_utc: datetime,
) -> List[dict]:
    """各局の気温・降水データを集計して返す。"""
    # 全時刻の map データを取得（新→古）
    maps: Dict[str, dict] = {}
    for ts in ts_list:
        data = _fetch(f"{MAP_BASE_URL}/{ts}.json")
        if data:
            maps[ts] = data
    print(f"[INFO] maps fetched: {len(maps)}/{len(ts_list)}")

    results = []
    for code, name in akita.items():
        # 最新値
        latest_entry = maps.get(ts_list[0], {}).get(code, {}) if ts_list else {}
        temp = _val(latest_entry, "temp")

        daily_temps: List[float] = []
        rn_by_hour: List[Tuple[datetime, float]] = []

        for ts_str, map_data in maps.items():
            ts_utc = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            entry = map_data.get(code, {})
            t_val = _val(entry, "temp")
            rn_val = _val(entry, "rn")
            if t_val is not None and ts_utc >= jst_today_start_utc:
                daily_temps.append(t_val)
            if rn_val is not None:
                rn_by_hour.append((ts_utc, rn_val))

        max_temp = max(daily_temps) if daily_temps else None
        min_temp = min(daily_temps) if daily_temps else None

        # 降水積算（新→古の順でスライス）
        rn_sorted = sorted(rn_by_hour, key=lambda x: x[0], reverse=True)
        rn3h = sum(v for _, v in rn_sorted[:3])
        rn24h = sum(v for _, v in rn_sorted[:24])

        results.append({
            "code": code,
            "name": name,
            "temp": temp,
            "max_temp": max_temp,
            "min_temp": min_temp,
            "rn3h": rn3h,
            "rn24h": rn24h,
        })

    return results


# =============================================================================
# 全国ランキング
# =============================================================================

def _ranking(latest_ts: str, table: dict) -> Tuple[list, list]:
    data = _fetch(f"{MAP_BASE_URL}/{latest_ts}.json") or {}
    entries = []
    for code, obs in data.items():
        t = _val(obs, "temp")
        if t is not None and code in table:
            entries.append((code, table[code].get("kjName", code), t))
    hot = sorted(entries, key=lambda x: x[2], reverse=True)[:RANK_TOP_N]
    cold = sorted(entries, key=lambda x: x[2])[:RANK_TOP_N]
    return hot, cold


# =============================================================================
# Discord フォーマット
# =============================================================================

def _tf(v: Optional[float], unit: str = "℃") -> str:
    return f"{v:.1f}{unit}" if v is not None else "---"


def _fmt_akita(results: List[dict], jst_now: datetime) -> str:
    lines = [
        f"🌡️ **アメダス 秋田県**　{jst_now.strftime('%m/%d %H:%M')} JST",
        "```",
        "地点       気温  日最高  日最低  3h雨  24h雨",
        "─" * 46,
    ]
    for r in results:
        t   = _tf(r["temp"]).rjust(6)
        mx  = _tf(r["max_temp"]).rjust(6)
        mn  = _tf(r["min_temp"]).rjust(6)
        r3  = _tf(r["rn3h"], "mm").rjust(6)
        r24 = _tf(r["rn24h"], "mm").rjust(7)
        name = r["name"][:5]  # 最大5文字（余白はコードブロック内で調整）
        lines.append(f"{name:<6}{t}  {mx}  {mn}  {r3}  {r24}")
    lines.append("```")
    return "\n".join(lines)


def _fmt_ranking(hot: list, cold: list, jst_now: datetime) -> str:
    ts = jst_now.strftime("%m/%d %H:%M")
    lines = [
        f"🏆 **全国気温ランキング**　{ts} JST",
        "",
        f"🔥 最高気温 TOP{RANK_TOP_N}",
        "```",
    ]
    for i, (_, name, t) in enumerate(hot, 1):
        lines.append(f"{i:>2}. {name:<8} {t:.1f}℃")
    lines += [
        "```",
        "",
        f"🥶 最低気温 TOP{RANK_TOP_N}",
        "```",
    ]
    for i, (_, name, t) in enumerate(cold, 1):
        lines.append(f"{i:>2}. {name:<8} {t:.1f}℃")
    lines.append("```")
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
    print(f"[INFO] 秋田県局: {len(akita)} stations")

    # 過去24時間の正時タイムスタンプ
    ts_list = _hourly_ts_list(latest_utc, 24)

    # JST 当日 0時の UTC（日最高/最低の起算点）
    jst_today_start = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    jst_today_start_utc = jst_today_start.astimezone(timezone.utc)

    # データ集計
    results = _collect(akita, ts_list, jst_today_start_utc)

    # 全国ランキング
    hot, cold = _ranking(latest_ts, table)

    # Discord 配信
    _post(_fmt_akita(results, jst_now))
    _post(_fmt_ranking(hot, cold, jst_now))

    print("=== Done ===")


if __name__ == "__main__":
    main()
