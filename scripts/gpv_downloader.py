# scripts/gpv_downloader.py
# ===============================
# 気象庁GPV自動ダウンロード&GRIB2→NetCDF変換モジュール
# 複数ファイルパターン/ミラーURL/リトライ対応・拡張可
# ===============================

import os
import urllib.request
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# --- ミラーURL（必要ならここに追加でOK！） ---
# --- 代表的な気象庁GPVファイルパターン ---
GPV_PATTERNS = [
    # GSM（日本域 0.1度, 気圧面/地上/土壌/積雪等）
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",   # 気圧面
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",    # 地上
    "GSM_GPV_Rjp_Gll0p1deg_Lsoil_FD0000-0100_grib2.bin",    # 土壌
    "GSM_GPV_Rjp_Gll0p1deg_Lsnow_FD0000-0100_grib2.bin",    # 積雪

    # MSM（日本域 0.05度, 気圧面/地上/土壌/積雪等）
    "MSM_GPV_Rjp_L-pall_FD0000-0100_grib2.bin",             # 気圧面
    "MSM_GPV_Rjp_Lsurf_FD0000-0100_grib2.bin",              # 地上
    "MSM_GPV_Rjp_Lsoil_FD0000-0100_grib2.bin",              # 土壌
    "MSM_GPV_Rjp_Lsnow_FD0000-0100_grib2.bin",              # 積雪

    # MSM（領域限定/短時間予報/アンサンブルなどがあればここに追加）
    # "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",  # 例: 先取り短時間
    # "MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
]

# --- ファイルパターン例（必要なだけ増やせる） ---
GPV_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FD0000-0100_grib2.bin",
    # 必要に応じて他もここに追加
]

def download_gpv_all(patterns=GPV_PATTERNS, base_dir="./data", mirrors=GPV_MIRROR_URLS, hours=[18,12,6,0], days=2):
    """
    patterns: ファイル名パターンのリスト
    mirrors: 参照するミラーURLリスト
    hours: 検索する時刻（JST基準）
    days: 今日から何日前まで試行するか
    """
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
    """
    1ファイルパターン＋複数ミラーでリトライ
    """
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
