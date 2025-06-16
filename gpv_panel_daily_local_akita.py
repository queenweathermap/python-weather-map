# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地 MSMパネル（6段×12列）全FH帯ループDL・ペア揃い優先
# --------------------------------------------------------
# 1. MSM GPVデータ（各FH帯/L-pall・Lsurf）を全部DL
# 2. 揃ったペアのみNetCDF変換→xarray合成
# 3. データあればパネル描画、なければNO DATA画像
# --------------------------------------------------------
# 2025-06-18 by ChatGPT（講座・実運用をもとに最適化）
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from module.utils.gpv_html_parser import find_existing_msm_pairs
from gpv_downloader import (
    download_available_gpv, grib2_to_nc, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

# ========================================
# 設定
# ========================================
BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "akita_local_msm_map.jpg"

# MSM日本域 予報時刻帯リスト（常にこの順でDL）
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

# ========================================
# ダミー時刻リスト（NO DATAパネル用）
# ========================================
def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 3, 6, 9, 12, 15, 18, 21] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

# ========================================
# MSM GPV 全FH帯L-pall/LsurfペアDL
# ========================================
def find_latest_matched_pairs(periods, base_dir, mirrors):
    """
    各FH帯ごとにL-pall/Lsurfの両方DLできたペアだけ返す
    戻り値：[(l_pall_grib2, lsurf_grib2, init_time, fh_band), ...]
    """
    matched = []
    for fh in periods:
        l_pall_pattern  = f"MSM_GPV_Rjp_L-pall_{fh}"
        lsurf_pattern   = f"MSM_GPV_Rjp_Lsurf_{fh}"
        l_pall_path, itime1 = download_available_gpv(l_pall_pattern, base_dir, mirrors)
        lsurf_path, itime2  = download_available_gpv(lsurf_pattern, base_dir, mirrors)
        # 両方DL成功＆イニシャル一致のみ採用
        if l_pall_path and lsurf_path and itime1 == itime2 and itime1 is not None:
            matched.append((l_pall_path, lsurf_path, itime1, fh))
    return matched

# ========================================
# メイン
# ========================================
try:
    os.makedirs(BASE_DIR, exist_ok=True)

    # 1. 各FH帯DL＆ペア揃いだけ使う
    matched_pairs = find_latest_matched_pairs(MSM_FORECAST_PERIODS, BASE_DIR, GPV_MIRROR_URLS)
    if not matched_pairs:
        print("【NO DATA】L-pall/Lsurfペアそろわず")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 2. 一番新しいペアだけ使う（init_time降順ソート）
    l_pall_grib2, lsurf_grib2, init_time, fh_band = sorted(matched_pairs, key=lambda x: x[2], reverse=True)[0]
    print(f"[INFO] 使用FH帯: {fh_band}, init_time: {init_time}")

    # 3. GRIB2→NetCDF変換（両方）
    nc_paths = []
    for path in [l_pall_grib2, lsurf_grib2]:
        nc = grib2_to_nc(path)
        if nc:
            nc_paths.append(nc)
    if len(nc_paths) < 2:
        print("【NO DATA】NetCDF変換失敗")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(0)

    # 4. NetCDF→xarray合成
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # 5. 描画時刻リスト
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
        print("【NO DATA】時刻データ不足")
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
