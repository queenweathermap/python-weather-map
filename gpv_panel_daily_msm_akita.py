# gpv_panel_daily_msm_akita.py
# ========================================================
# MSM秋田局地天気図パネル（6段×12列）自動生成スクリプト
# 必須: gpv_downloader.py, panel_utils.py
# ========================================================

import sys
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    MSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12

if __name__ == "__main__":
    try:
        print("=== 秋田局地MSMパネル処理開始 ===")
        init_dt = find_existing_init_dt(MSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 3, 6, 9, 12, 15, 18, 21])
        print("MSM最新イニシャル時刻:", init_dt)
        if init_dt is None:
            print("NO DATA: MSMファイルがサーバに見つかりません")
            # NO DATAパネル生成
            sys.exit(0)

        panel_files = download_gpv_panel(MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        # 空でない時刻だけ
        pattern_files = [f for f in panel_files if f and len(f) == len(MSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 3:
            print("NO DATA: pattern_files is None or <3")
            # NO DATAパネル生成
            sys.exit(0)

        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files for item in sublist]
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_nc(path)
            if os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        print("nc_paths:", nc_paths)

        if not nc_paths or len(nc_paths) < 3:
            print("NO DATA: ncファイル少なすぎ")
            # NO DATAパネル生成
            sys.exit(0)

        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 3:
            print("NO DATA: ds_list少なすぎ")
            # NO DATAパネル生成
            sys.exit(0)

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = ds.time.values[:NCOLS]

        make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
