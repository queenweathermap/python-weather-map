# gpv_panel_daily_msm_akita.py
# ========================================================
# MSM秋田局地天気図パネル（6段×12列）自動生成スクリプト
# ========================================================

import sys
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import (
    find_nearest_init, download_gpv_panel,
    grib2_to_nc, MSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import make_nodata_weather_panel, make_local_weather_panel, align_datasets_common

BASE_DIR = "./data"
NCOLS = 12

if __name__ == "__main__":
    try:
        print("=== 秋田局地MSMパネル処理開始 ===")
        init_dt = find_nearest_init()
        print(f"init_dt: {init_dt}")

        panel_files = download_gpv_panel(MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)
        pattern_files = [f for f in panel_files if len(f) == len(MSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 3:
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path="akita_panel_nodata.jpg")
            print("【ERROR】秋田局地 MSM GPVデータ未取得。NO DATAパネル生成")
            sys.exit(0)  # ← ここを0に

        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files[:3] for item in sublist]
        nc_paths = [grib2_to_nc(path) for path, _ in file_list]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")

        if len(ds.time) == 0:
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path="akita_panel_nodata.jpg")
            print("【ERROR】秋田局地 MSM GPVに有効データ無し。NO DATAパネル生成")
            sys.exit(0)  # ← ここも0に
        times = ds.time.values[:NCOLS]
        print("times:", times)

        make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
