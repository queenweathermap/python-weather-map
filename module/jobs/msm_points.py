# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/msm_points.py
#
# 気象庁MSM(メソモデル)数値予報の格子点値を、アメダス観測地点ごとに取り出し、
# 地域(アメダス局コード先頭2桁)別のJSONにして R2 に置く。会員向けPWAの
# 「MSM 数値予報」の表が、このJSONを読んで表示する。
#
# ★格子点値(約5km)を観測地点の最寄り格子で取り出したもの。統計的な補正(ガイダンス)や
#   標高補正はしていない。気象庁の予報・実況とは異なる。天気の記号などの
#   「予想の判断」は含めない(数値のみ)。
#
# データ: 京都大学生存圏研究所のMSM GPVアーカイブ(module/jobs/msm_weather.py と共通)
#
# R2のキー(R2_PREFIX=msm-points を想定):
#   manifest.json                      {"init": "20260930090000", ...}  (短いキャッシュ。PWAが最初に読む)
#   {init}/{prefix}.json               地域別の時系列
# 実行: python scripts/msm_points.py   (MSM_POINTS_OUT_DIR を指定するとR2ではなくローカルに書く)
# =============================================================================

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from module.jobs.msm_weather import (
    DLAT, DLON, LAT0, LON0, MSM_FILES, NLAT, NLON, RISH_BASE, _SSL_CTX, _download, find_latest_init,
)

AMEDAS_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
MAX_FT = 39
OUT_DIR = os.environ.get("MSM_POINTS_OUT_DIR", "").strip()
KEEP_INITS = int(os.environ.get("MSM_POINTS_KEEP_INITS", "2"))


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "177chart-msm-points/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _stations() -> List[Tuple[str, str, float, float]]:
    """アメダス局: (コード, 名称, 緯度, 経度)。MSMの範囲内(日本付近)のものだけ。"""
    tb = _get_json(AMEDAS_TABLE_URL)
    out = []
    for code, v in sorted(tb.items()):
        lat = v["lat"][0] + v["lat"][1] / 60.0
        lon = v["lon"][0] + v["lon"][1] / 60.0
        if LAT0 - (NLAT - 1) * DLAT <= lat <= LAT0 and LON0 <= lon <= LON0 + (NLON - 1) * DLON:
            out.append((code, v.get("kjName", code), lat, lon))
    return out


def _idx(lat: float, lon: float) -> Tuple[int, int]:
    i = int(round((LAT0 - lat) / DLAT))
    j = int(round((lon - LON0) / DLON))
    return min(max(i, 0), NLAT - 1), min(max(j, 0), NLON - 1)


def extract(init: datetime, stations) -> Dict[str, Dict[int, List[float]]]:
    """{"t","rh","u","v","tc","p1": {FT: [局ごとの値...]}} を返す(局の順序はstationsと同じ)。"""
    import pygrib
    import numpy as np

    ii = np.array([_idx(la, lo)[0] for _, _, la, lo in stations])
    jj = np.array([_idx(la, lo)[1] for _, _, la, lo in stations])
    out: Dict[str, Dict[int, List[float]]] = {k: {} for k in ("t", "rh", "u", "v", "tc", "p1")}
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
                cat, num, lev = m.parameterCategory, m.parameterNumber, m.typeOfLevel
                if (cat, num) == (0, 0) and lev == "heightAboveGround":
                    key = "t"
                elif (cat, num) == (1, 1) and lev == "heightAboveGround":
                    key = "rh"
                elif (cat, num) == (2, 2):
                    key = "u"
                elif (cat, num) == (2, 3):
                    key = "v"
                elif (cat, num) == (6, 1):
                    key = "tc"
                elif (cat, num) == (1, 8):
                    key = "p1"
                else:
                    continue
                ft = int(str(m.stepRange).split("-")[-1]) if key == "p1" else m.forecastTime
                if ft > MAX_FT:
                    continue
                vals = m.values[ii, jj]
                out[key][ft] = [float(x) for x in vals]
            g.close()
    return out


def _q(x: float, scale: float) -> int:
    return int(round(x * scale))


def build_regions(init: datetime, stations, data) -> Dict[str, dict]:
    """局コード先頭2桁ごとのJSONを作る(軽くするため整数に量子化)。"""
    fts = [ft for ft in range(0, MAX_FT + 1) if ft in data["t"]]
    regions: Dict[str, dict] = {}
    for k, (code, name, la, lo) in enumerate(stations):
        t, rh, tc, p, ws, wd = [], [], [], [], [], []
        for ft in fts:
            t.append(_q(data["t"][ft][k] - 273.15, 10))
            rh.append(_q(data["rh"][ft][k], 1) if ft in data["rh"] else None)
            tc.append(_q(data["tc"][ft][k], 1) if ft in data["tc"] else None)
            p.append(_q(data["p1"][ft][k], 10) if ft in data["p1"] else 0)       # ft時間目の1時間降水量(ft-1〜ft時間)
            if ft in data["u"] and ft in data["v"]:
                u, v = data["u"][ft][k], data["v"][ft][k]
                ws.append(_q(math.hypot(u, v), 10))
                wd.append(int(round((math.degrees(math.atan2(-u, -v)) % 360) / 22.5)) % 16)   # 風が吹いてくる方向(16方位、0=北)
            else:
                ws.append(None)
                wd.append(None)
        reg = regions.setdefault(code[:2], {
            "init": init.strftime("%Y-%m-%dT%H:%M:%SZ"), "fts": fts,
            "units": {"t": "0.1℃", "rh": "%", "tc": "%", "p": "0.1mm/h", "ws": "0.1m/s", "wd": "16方位(0=北)"},
            "stations": {},
        })
        reg["stations"][code] = {"n": name, "la": round(la, 2), "t": t, "rh": rh, "tc": tc, "p": p, "ws": ws, "wd": wd}
    return regions


# -----------------------------------------------------------------------------
# 出力(R2 または ローカル)
# -----------------------------------------------------------------------------

def _write(key: str, data: bytes, cache: str) -> None:
    if OUT_DIR:
        path = os.path.join(OUT_DIR, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        print(f"[OK] write {path}  {len(data):,} bytes")
        return
    from module.utils.r2_utils import put_bytes
    put_bytes(key, data, content_type="application/json; charset=utf-8", cache_control=cache)
    print(f"[OK] R2 {key}  {len(data):,} bytes")


def _current_manifest_init() -> Optional[str]:
    if OUT_DIR:
        p = os.path.join(OUT_DIR, "manifest.json")
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8")).get("init")
        return None
    from module.utils.r2_utils import get_bytes
    raw = get_bytes("manifest.json")
    return json.loads(raw.decode("utf-8")).get("init") if raw else None


def _cleanup_old(keep_init: str) -> None:
    """古い初期時刻のフォルダを削除する(新しい順にKEEP_INITS個を残す)。"""
    if OUT_DIR:
        return
    from module.utils.r2_utils import list_keys_with_prefix, delete_keys
    keys = list_keys_with_prefix("")
    inits = sorted({m.group(1) for k in keys for m in [re.match(r"^(\d{14})/", k)] if m})
    old = [i for i in inits[:-KEEP_INITS]] if len(inits) > KEEP_INITS else []
    doomed = [k for k in keys if any(k.startswith(i + "/") for i in old)]
    if doomed:
        print(f"[INFO] 古い初期時刻を削除: {old} ({len(doomed)}件)")
        delete_keys(doomed)


def main() -> None:
    try:
        import pygrib  # noqa: F401
    except ImportError:
        raise SystemExit("[ERR] pygrib 未インストール")
    init = find_latest_init()
    if not init:
        raise SystemExit("[ERR] MSMの初期時刻が見つからない")
    init14 = init.strftime("%Y%m%d%H%M%S")
    if _current_manifest_init() == init14 and os.environ.get("MSM_POINTS_FORCE", "") != "1":
        print(f"[INFO] 初期時刻 {init14} は処理済み — スキップ")
        return
    stations = _stations()
    print(f"[INFO] アメダス局 {len(stations)} 件、初期時刻 {init14}")
    data = extract(init, stations)
    regions = build_regions(init, stations, data)
    for prefix, doc in sorted(regions.items()):
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        _write(f"{init14}/{prefix}.json", body, "public, max-age=3600")
    manifest = {
        "init": init14,
        "initISO": init.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prefixes": sorted(regions),
        "note": "気象庁MSM数値予報の格子点値(約5km)を、アメダス観測地点の最寄り格子で取り出したもの。統計的な補正や標高補正はしていない。",
    }
    # 地域ファイルをすべて置いてから、最後にmanifestを更新する(PWAが中途半端な状態を見ないように)
    _write("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "public, max-age=60, must-revalidate")
    _cleanup_old(init14)
    print("=== Done ===")
