# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地 MSMパネル（6段×12列）全FH帯ループDL・ペア揃い優先
# --------------------------------------------------------
# 1. MSM GPVデータ（各FH帯/L-pall・Lsurf）を全部DL
# 2. 揃ったペアのみNetCDF変換→xarray合成
# 3. データあればパネル描画、なければNO DATA画像
# --------------------------------------------------------
# 2025-06-18 by ChatGPT
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from gpv_downloader import (
    download_available_gpv, grib2_to_nc,
    GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "akita_local_msm_map.jpg"

# MSM日本域 予報時刻帯リスト
MSM_FORECAST_PERIODS = [
    "FH00-15",
    "FH16-33",
    "FH34-39",
    "FH40-51",
    "FH52-78",
]

PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 3, 6, 9, 12, 15, 18, 21] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

def find_latest_matched_pairs(periods, base_dir, mirrors):
    """
    各FH帯ごとにL-pall/Lsurfの両方DLできたペアだけを返す
    戻り値：[(l_pall_grib2, lsurf_grib2, init_time, fh_band), ...]
    """
    matched = []
    for fh in periods:
        l_pall_pattern  = f"MSM_GPV_Rjp_L-pall_{fh}"
        lsurf_pattern   = f"MSM_GPV_Rjp_Lsurf_{fh}"

        l_pall_path, itime1 = download_available_gpv(l_pall_pattern, base_dir, mirrors)
        lsurf_path, itime2  = download_available_gpv(lsurf_pattern, base_dir, mirrors)

        # 両方DLできて、初期時刻が一致するものだけ採用
        if l_pall_path and lsurf_path and itime1 == itime2 and itime1 is not None:
            matched.append((l_pall_path, lsurf_path, itime1, fh))
    return matched

try:
    os.makedirs(BASE_DIR, exist_ok=True)

    # --- 全FH帯ループでペアを揃える ---
    matched_pairs = find_latest_matched_pairs(MSM_FORECAST_PERIODS, BASE_DIR, GPV_MIRROR_URLS)
    if not matched_pairs:
        print("【NO DATA】L-pall/Lsurfの両方揃ったFH帯なし。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # --- 最新ペアを選ぶ（原則一番新しいinit_timeのもの）---
    l_pall_grib2, lsurf_grib2, init_time, fh_band = sorted(matched_pairs, key=lambda x: x[2], reverse=True)[0]
    print(f"[INFO] 使用FH帯: {fh_band}, init_time: {init_time}")

    # --- GRIB2→NetCDF変換（両方）---
    nc_paths = []
    for path in [l_pall_grib2, lsurf_grib2]:
        nc = grib2_to_nc(path)
        if nc:
            nc_paths.append(nc)
    if len(nc_paths) < 2:
        print("【NO DATA】NetCDF変換失敗。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # --- xarray Datasetで2つ結合 ---
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # --- 描画用時刻リスト ---
    times = ds.time.values[:NCOLS]

    # --- プロット関数リスト ---
    from module.gpv_plotter_msm import (
        plot_emagram_msm_panel,
        plot_700hpa_dindex_500hpa_temp_msm,
        plot_850hpa_temp_wind_700hpa_w_msm,
        plot_850hpa_thetae_stream_msm,
        plot_925hpa_temp_wind_dindex_msm,
        plot_surface_pressure_and_wind_msm,
    )
    plot_func_list = [
        plot_emagram_msm_panel,
        plot_700hpa_dindex_500hpa_temp_msm,
        plot_850hpa_temp_wind_700hpa_w_msm,
        plot_850hpa_thetae_stream_msm,
        plot_925hpa_temp_wind_dindex_msm,
        plot_surface_pressure_and_wind_msm,
    ]

    # --- 描画 or NO DATA ---
    if len(times) >= NCOLS:
        make_local_weather_panel(
            ds, times, OUTFILE,
            pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
            lat_range=(38, 41), lon_range=(139, 142),
            plot_func_list=plot_func_list,
            nrows=6, ncols=NCOLS,
        )
        print("天気図パネル画像を正常に出力しました")
    else:
        print("【NO DATA】時刻データ不足。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

except Exception as e:
    print("【NO DATA】例外:", e)
    traceback.print_exc()
    make_nodata_weather_panel(
        save_path=OUTFILE,
        city_name=CITY_NAME,
        times=get_gpv_nodata_times(NCOLS)
    )
    sys.exit(0)
