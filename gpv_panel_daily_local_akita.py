# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地 MSMパネル（6段×12列）全FH帯DL・index.htmlパース自動化
# どちらか単独（L-pall/Lsurf）でもパネル生成可
# 2025-06-18 by ChatGPT（講座・実運用ベース最適化）
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from module.utils.gpv_html_parser import find_existing_msm_files
from gpv_downloader import grib2_to_nc
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
OUTFILE = "akita_local_msm_map.jpg"
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
YMD = pd.Timestamp.now().strftime("%Y%m%d")
NCOLS = 12

PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 3, 6, 9, 12, 15, 18, 21] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)

    # 1. サーバindex.htmlからL-pall/Lsurfファイルを抽出（どちらかだけでもOK）
    files = find_existing_msm_files(BASE_URL, YMD)
    if not files:
        print("NO DATA: サーバ上にファイルが見つかりません")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 2. 最新init時刻のものをNCOLS件ピックアップ（どちらかあれば採用）
    latest_init = max([f["init"] for f in files])
    use_files = [f for f in files if f["init"] == latest_init][:NCOLS]
    if not use_files or len(use_files) < 2:
        print("NO DATA: 有効ファイル不足")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 3. NetCDF変換（どちらかだけでも揃った分だけ）
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
    if not nc_paths or len(nc_paths) < 1:
        print("NO DATA: NetCDF変換失敗")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 4. xarrayで合成（利用可能な分だけ）
    ds_list = []
    for nc in nc_paths:
        try:
            ds = xr.open_dataset(nc)
            ds_list.append(ds)
        except Exception as e:
            print(f"[WARN] open_dataset失敗: {nc} ({e})")
    if not ds_list or len(ds_list) < 1:
        print("NO DATA: Dataset不足")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    ds = align_datasets_common(ds_list, ncols=NCOLS)
    times = ds.time.values[:NCOLS] if hasattr(ds, "time") else get_gpv_nodata_times(NCOLS)

    # 5. MSM描画関数リスト
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

    # 6. パネル描画/NO DATA分岐
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
        print("NO DATA: 時刻データ不足")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

except Exception as e:
    print("NO DATA: Exception", e)
    traceback.print_exc()
    make_nodata_weather_panel(
        save_path=OUTFILE,
        city_name=CITY_NAME,
        times=get_gpv_nodata_times(NCOLS)
    )
    sys.exit(1)
