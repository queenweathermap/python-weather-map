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

    for pattern in GSM_PATTERNS:
        grib2_path, itime = download_available_gpv(pattern, BASE_DIR, GPV_MIRROR_URLS)
        if grib2_path is not None and itime is not None:
            grib2_files.append(grib2_path)
            if init_time is None:
                init_time = itime

    if len(grib2_files) < 2:
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    for path in grib2_files:
        nc = grib2_to_nc(path)
        if nc:
            nc_paths.append(nc)

    # NetCDFが2つ揃っているか
    if len(nc_paths) < 2:
        print("【NO DATA】NetCDF変換不良。ダミー画像出力")
        make_nodata_weather_panel(...)
        sys.exit(0)
    
    # NetCDF→xarray Datasetを一気に開く
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)
    
    # 十分な時刻データがあるか
    if len(ds.time) >= NCOLS:
        # プロット関数リストで天気図描画
        make_local_weather_panel(
            ds, times, OUTFILE,
            pin_lat=..., pin_lon=..., city_name=...,
            plot_func_list=plot_func_list, nrows=6, ncols=NCOLS,
        )
    else:
        make_nodata_weather_panel(...)

    
    # 天気図描画用プロット関数リストを用意（必須!!）
    from module.gpv_plotter_gsm import (
        plot_emagram_gsm_panel,
        plot_700hpa_dindex_500hpa_temp_gsm,
        plot_850hpa_temp_wind_700hpa_w_gsm,
        plot_850hpa_thetae_stream_gsm,
        plot_925hpa_temp_wind_dindex_gsm,
        plot_surface_pressure_and_wind_gsm,
    )
    plot_func_list = [
        plot_emagram_gsm_panel,
        plot_700hpa_dindex_500hpa_temp_gsm,
        plot_850hpa_temp_wind_700hpa_w_gsm,
        plot_850hpa_thetae_stream_gsm,
        plot_925hpa_temp_wind_dindex_gsm,
        plot_surface_pressure_and_wind_gsm,
    ]

    # 描画時刻リストも xarray から取得
    times = ds.time.values[:NCOLS]
    
    # パネル描画実行（plot_func_list渡すこと！）
    make_local_weather_panel(
        ds, times, OUTFILE,
        pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
        lat_range=(38, 41), lon_range=(139, 142),
        plot_func_list=plot_func_list,
        nrows=6, ncols=NCOLS,
    )

    print("天気図パネル画像を正常に出力しました")

    except Exception as e:
        print("【NO DATA】例外:", e)
        traceback.print_exc()
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)
