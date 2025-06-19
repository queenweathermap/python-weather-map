# gpv_downloader.py
# --------------------------------------------------------
# GPVファイルのダウンロード・変換・イニシャル時刻探索ユーティリティ
# --------------------------------------------------------

import os
import urllib.request
import glob
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import pandas as pd

# ----------- 設定 ----------
GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall",
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf"
]

MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall",   # 上層データ
    "MSM_GPV_Rjp_Lsurf"     # 地上データ
]

def find_existing_init_dt(patterns, base_dir, mirror_urls, hours=[0, 12]):
    """
    直近3日分の指定時刻（例: 0, 12UTC）で必要な全パターンファイルが揃う
    最新のイニシャル時刻(dt)を返す。なければNone。
    """
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    for day_offset in range(0, 3):
        dt = now - pd.Timedelta(days=day_offset)
        for hour in sorted(hours, reverse=True):  # 12→0の順
            dt_h = dt.replace(hour=hour)
            all_exist = True
            for pattern in patterns:
                ymd = dt_h.strftime("%Y%m%d")
                h = dt_h.hour
                # 拡張子は .bin or .bin.nc どちらでもヒットするようにする
                g = glob.glob(os.path.join(
                    base_dir,
                    f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}*"
                ))
                if len(g) == 0:
                    all_exist = False
            if all_exist:
                return dt_h
    return None

def download_available_gpv(pattern, base_dir, mirrors):
    """
    サーバ上で最新のGPVファイルを探してDL
    """
    now = datetime.utcnow() + timedelta(hours=9)
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
        for h in [18, 12, 6, 0]:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            for url_base in mirrors:
                url = f"{url_base}/{y}/{m}/{d}/{fname}"
                out_path = os.path.join(base_dir, fname)
                print(f"[TRY] {url}")
                try:
                    urllib.request.urlretrieve(url, out_path)
                    print(f"[OK] DL: {out_path}")
                    return out_path, datetime(dt.year, dt.month, dt.day, h)
                except Exception as e:
                    print(f"[NG] {url.split('/')[-1]}: {e}")
    print(f"[ERROR] {pattern} どれもDLできず")
    return None, None

def grib2_to_nc(grib2_path):
    """
    GRIB2→NetCDF変換（wgrib2使用・サイズチェック付き）
    """
    grib2_path = Path(grib2_path)
    if not grib2_path.exists() or os.path.getsize(grib2_path) < 10 * 1024:
        print(f"[SKIP] ダウンロード失敗or空ファイル: {grib2_path}")
        return None
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[wgrib2] 実行: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8"
        )
        print("[wgrib2] stdout:", result.stdout)
        print("[wgrib2] stderr:", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        print(f"[wgrib2 error]: {e.stderr}")
        return None
    if not nc_path.exists() or os.path.getsize(nc_path) < 10 * 1024:
        print(f"[SKIP] NetCDF出力異常: {nc_path}")
        return None
    return str(nc_path)

# --------------------- メイン ---------------------
if __name__ == "__main__":
    base_dir = "./data"
    os.makedirs(base_dir, exist_ok=True)

    grib2_files = []
    nc_paths = []
    init_time = None

    for pattern in GSM_PATTERNS:
        grib2_path, itime = download_available_gpv(pattern, base_dir, GPV_MIRROR_URLS)
        if grib2_path is not None and itime is not None:
            grib2_files.append(grib2_path)
            if init_time is None:
                init_time = itime

    if len(grib2_files) < 2:
        print("【ERROR】気圧面・地上のGRIB2ファイルが両方揃いません（NO DATA）")
        exit(1)

    for path in grib2_files:
        nc = grib2_to_nc(path)
        if nc is not None:
            nc_paths.append(nc)

    if len(nc_paths) < 2:
        print("【ERROR】NetCDF変換が両方成功せず（NO DATA）")
        exit(1)

    print(f"[INFO] 2つのNetCDF OK: {nc_paths}")
    print(f"[INFO] Init time: {init_time}")
