# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地 MSMパネル（6段×12列）全FH帯DL・index.htmlパース自動化
# --------------------------------------------------------
# 1. サーバindex.htmlからL-pall/Lsurfペア抽出（最速・NO DATA激減）
# 2. 揃ったペアをDL→NetCDF変換→xarray合成
# 3. データがあればパネル描画、なければNO DATA画像
# 2025-06-18 by ChatGPT（講座・実運用ベース最適化）
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from module.utils.gpv_html_parser import find_existing_msm_pairs
from gpv_downloader import grib2_to_nc
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

# ========================================
# 設定
# ========================================
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

    # 1. サーバindex.htmlから最新ペアを抽出
    pairs = find_existing_msm_pairs(BASE_URL, YMD)
    if not pairs:
        print("NO DATA: サーバ上にペアが見つかりません")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 2. 一番新しいinit時刻のものから必要数だけピックアップ
    latest_init = max([p[2] for p in pairs])
    use_pairs = [p for p in pairs if p[2] == latest_init][:NCOLS]
    if len(use_pairs) < 2:
        print("NO DATA: 有効ペア不足")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 3. ペアごとにGRIB2→NetCDF変換
    nc_paths = []
    for l_pall_path, lsurf_path, init_time, fh_band in use_pairs:
        nc1 = grib2_to_nc(l_pall_path)
        nc2 = grib2_to_nc(lsurf_path)
        if nc1 and nc2:
            nc_paths.extend([nc1, nc2])
    if len(nc_paths) < 2:
        print("NO DATA: NetCDF変換失敗")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 4. xarrayで合成（全パネル分）
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # 5. 描画用時刻リスト
    times = ds.time.values[:NCOLS]

    # 6. パネル描画関数リスト（MSM用）
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

    # 7. パネル描画/NO DATA分岐
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
