# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地パネル（6段×12列）自動生成スクリプト（MSM対応・本番運用）
# --------------------------------------------------------
# 1. MSM GPVデータのDL＋NetCDF変換（最新イニシャル自動）
# 2. 2ファイル結合→時刻合わせ（xarray）
# 3. プロット関数リストで天気図パネル描画
# 4. データなければNO DATA画像
# --------------------------------------------------------
# 2025-06-18 by ChatGPT（講座動画・運用実績ベース）
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from gpv_downloader import (
    download_available_gpv, grib2_to_nc,
    MSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "akita_local_msm_map.jpg"

# 秋田ピンポイント
PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=12):
    """
    NO DATAパネル用のダミー時刻リスト生成（イニシャル時刻から3時間ごと）
    """
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 3, 6, 9, 12, 15, 18, 21] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    grib2_files, nc_paths, init_time = [], [], None

    # --- MSM_PATTERNSで2ファイルDL（秋田局地L-pall/Lsurf等を想定） ---
    for pattern in MSM_PATTERNS:
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

    # --- GRIB2→NetCDF変換 ---
    for path in grib2_files:
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

    # --- xarray Datasetとして一気に開く・結合 ---
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # --- 描画用時刻リストを抽出 ---
    times = ds.time.values[:NCOLS]

    # --- プロット関数リスト（秋田局地MSM用）---
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

    # --- 時刻データが十分あればパネル描画、なければNO DATA ---
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
