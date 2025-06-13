# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（12時刻×2パターン/日パネル）
# 必須: gpv_downloader.py, panel_utils.py
# ===============================================

import sys
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import find_existing_init_dt, download_gpv_panel, GSM_PATTERNS, GPV_MIRROR_URLS
from module.panel_utils import make_nodata_weather_panel, make_daily_weather_panel_multi_time, align_datasets_common

BASE_DIR = "./data"
NCOLS = 12

if __name__ == "__main__":
    try:
        print("1. データダウンロード開始")
        init_dt = find_nearest_init()  # 直近イニシャル時刻（自動）
        print(f"init_dt: {init_dt}")

        panel_files = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)
        pattern_files = [f for f in panel_files if len(f) == len(GSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, "gsm_panel_nodata.jpg")
            print("【ERROR】GPVファイル未取得。NO DATAパネル送信処理へ…")
            sys.exit(0)  # ← ここを0に

        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files[:2] for item in sublist]
        nc_paths = [grib2_to_nc(path) for path, _ in file_list]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = ds.time.values[:NCOLS]

        make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
