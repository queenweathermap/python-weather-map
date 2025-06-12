# gpv_downloader.py
# ===============================
# 気象庁GPV自動ダウンロード&GRIB2→NetCDF変換モジュール
# GSMはFD、MSMはFH分割対応／ファイルパターン拡張可
# ===============================

import os
import urllib.request
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

# --- GSM用パターン（FD） ---
GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",    # 気圧面
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",     # 地上
    # 土壌や積雪も必要なら追加
]

# --- MSM用パターン（FH分割） ---
MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH36-39_grib2.bin",
]

def download_gpv_all(patterns, base_dir="./data", mirrors=GPV_MIRROR_URLS, hours=[18,12,6,0], days=2):
    os.makedirs(base_dir, exist_ok=True)
    downloaded = []
    for pattern in patterns:
        file_path, file_time = download_gpv_single(pattern, base_dir, mirrors, hours, days)
        if file_path is not None:
            downloaded.append((file_path, file_time))
        else:
            print(f"[FAIL] {pattern} のダウンロード失敗")
    return downloaded

def download_gpv_single(pattern, base_dir, mirrors, hours, days):
    now = datetime.utcnow() + timedelta(hours=9)
    tried = []
    for day_offset in range(days):
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
        for h in hours:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            for url_base in mirrors:
                url = f"{url_base}/{y}/{m}/{d}/{fname}"
                out_path = os.path.join(base_dir, fname)
                tried.append(url)
                try:
                    urllib.request.urlretrieve(url, out_path)
                    print(f"[OK] DL: {out_path}")
                    return out_path, datetime(dt.year, dt.month, dt.day, h)
                except Exception as e:
                    print(f"[NG] {fname}@{url_base}: {e}")
    print("DL失敗 試行URL:", *tried, sep="\n- ")
    return None, None

def grib2_to_nc(grib2_path):
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError("grib2→nc変換に失敗")
    return str(nc_path)

# 利用例（mainから呼び出し）
# files = download_gpv_all(GSM_PATTERNS, base_dir="./data")
# for grib2_path, init_time in files:
#     nc_path = grib2_to_nc(grib2_path)
#     # ...続き
