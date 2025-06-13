# gpv_panel_daily_msm.py
# ===============================================
# MSM天気図 6行×n列パネル生成スクリプト
# 必須: gpv_downloader.py, panel_utils.py, gpv_plotter_msm.py など
# 2025-06-13 by ChatGPT
# ===============================================

import sys
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import (
    download_gpv_panel, grib2_to_nc, find_nearest_init,
    GPV_MIRROR_URLS, MSM_PATTERNS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common
)
from module.gpv_plotter_msm import (
    plot_500hpa_vorticity_msm,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)

BASE_DIR = "./data"
NCOLS = 12  # 列数は必要に応じて調整可

if __name__ == "__main__":
    try:
        print("=== MSMパネル処理開始 ===")
        init_dt = find_nearest_init()
        print(f"init_dt: {init_dt}")

        panel_files = download_gpv_panel(MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        pattern_files = [f for f in panel_files if len(f) == len(MSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 3:
            print("NO DATA: pattern_files is None or <3")
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, "msm_panel_nodata.jpg")
            print("【ERROR】MSM GPVファイル未取得。NO DATAパネル送信処理へ…")
            sys.exit(1)

        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files[:3] for item in sublist]
        nc_paths = [grib2_to_nc(path) for path, _ in file_list]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds
                print(f"[修正] ds_list[{i}]のtimeをdatetime64[ns]に揃えました")

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        print("xr.merge OK")
        print("ds.time.values:", ds.time.values)
        print("len(ds.time):", len(ds.time.values))

        times = ds.time.values[:NCOLS]
        print("times:", times)

        # MSM天気図パネル作成（ここで個別パネル描画用の関数リストも渡せます）
        # plot_func_list例: [plot_500hpa_vorticity_msm, ...] × 行数ぶん
        # もし1枚ごとに異なる描画ならpanel_utils側を拡張する形でも可
        make_daily_weather_panel_multi_time(ds, times, "msm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
