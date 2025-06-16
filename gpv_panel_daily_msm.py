# gpv_panel_daily_msm.py
# ========================================================
# MSMパネル自動生成スクリプト（6行×12列パネル・全国域MSM用/HTMLパースDL）
# ・MSM GPVデータ（L-pall/Lsurfいずれか単独でもOK）を自動DL
# ========================================================

import os
import sys
import traceback
import pandas as pd
import xarray as xr

from module.utils.gpv_html_parser import find_existing_msm_files
from gpv_downloader import grib2_to_nc
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

BASE_DIR = "./data"
OUTFILE = "msm_weather_map.jpg"
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
YMD = pd.Timestamp.now().strftime("%Y%m%d")
NCOLS = 12

def get_nodata_times(ncols=NCOLS):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    return [now + pd.Timedelta(hours=3 * i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)

    print("=== MSMパネル自動処理（HTMLパースDL）開始 ===")
    files = find_existing_msm_files(BASE_URL, YMD)
    if not files:
        print("NO DATA: サーバ上にファイルが見つかりません")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    latest_init = max([f["init"] for f in files])
    use_files = [f for f in files if f["init"] == latest_init][:NCOLS]
    if not use_files or len(use_files) < 2:
        print("NO DATA: 有効ファイル不足")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    nc_paths = []
    for f in use_files:
        if f["l_pall_url"]:
            nc1 = grib2_to_nc(f["l_pall_url"])
            if nc1:
                nc_paths.append(nc1)
        if f["lsurf_url"]:
            nc2 = grib2_to_nc(f["lsurf_url"])
            if nc2:
                nc_paths.append(nc2)
    if not nc_paths:
        print("NO DATA: NetCDF変換失敗")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    ds_list = []
    for nc in nc_paths:
        try:
            ds = xr.open_dataset(nc)
            ds_list.append(ds)
        except Exception as e:
            print(f"[WARN] open_dataset失敗: {nc} ({e})")
    if not ds_list:
        print("NO DATA: Dataset不足")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    ds = align_datasets_common(ds_list, ncols=NCOLS)
    times = ds.time.values[:NCOLS] if hasattr(ds, "time") else get_nodata_times(NCOLS)

    make_daily_weather_panel_multi_time(ds, times, OUTFILE)
    print("画像生成完了\n=== 完了 ===")

except Exception as e:
    print("=== 重大エラー発生 ===")
    print(type(e), e)
    traceback.print_exc()
    make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
    sys.exit(1)
