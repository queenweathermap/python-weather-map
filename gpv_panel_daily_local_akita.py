# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地パネル（6段×12列）自動生成スクリプト（GSM版：DL部改良）
# 2025-06-18 by ChatGPT
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from gpv_downloader import (
    download_available_gpv, grib2_to_nc,
    GSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "akita_local_msm_map.jpg"

# 秋田市（ピンポイント座標・地名）
PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    grib2_files, nc_paths, init_time = [], [], None

    # GSM_PATTERNS = [気圧面, 地上]（2ファイル個別に最新DL）
    for pattern in GSM_PATTERNS:
        grib2_path, itime = download_available_gpv(pattern, BASE_DIR, GPV_MIRROR_URLS)
        if grib2_path is not None and itime is not None:
            grib2_files.append(grib2_path)
            if init_time is None:
                init_time = itime

    if len(grib2_files) < 2:
        print("【NO DATA】2ファイルそろわず。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # GRIB2→NetCDF変換
    for path in grib2_files:
        nc = grib2_to_nc(path)
        if nc:
            nc_paths.append(nc)

    if len(nc_paths) < 2:
        print("【NO DATA】NetCDF変換不良。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # データ結合・共通時刻合わせ
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # 時刻リスト
    times = ds.time.values[:NCOLS]

    # パネル描画（ここで好きなプロット関数を指定可能）
    # TODO: plot_func_listはお手元のplotterに合わせてください
    make_local_weather_panel(
        ds, times, OUTFILE,
        pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
        lat_range=(38, 41), lon_range=(139, 142),    # 秋田周辺範囲
        plot_func_list=None,   # プロット関数リストを指定
        nrows=6, ncols=NCOLS,
    )

except Exception as e:
    print("【NO DATA】例外:", e)
    traceback.print_exc()
    make_nodata_weather_panel(
        save_path=OUTFILE,
        city_name=CITY_NAME,
        times=get_gpv_nodata_times(NCOLS)
    )
    sys.exit(0)
