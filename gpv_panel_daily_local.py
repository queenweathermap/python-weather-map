# gpv_panel_daily_local.py
# ===============================================================
# 任意の地点でGSM/MSM局地天気図パネル（エマグラム付き）を生成する汎用スクリプト
# ---------------------------------------------------------------
# ・モデル・地点・範囲を指定し自動描画
# ・MSMはindex.htmlパースでL-pall/Lsurfいずれか単独でも描画
# ---------------------------------------------------------------
# 2025-06-18 by ChatGPT
# ===============================================================

import sys
import traceback
import argparse
import os
import pandas as pd
import xarray as xr

from module.utils.gpv_html_parser import find_existing_msm_files  # ★関数名を単独ファイル対応に
from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    MSM_PATTERNS, GSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    align_datasets_common,
    make_local_weather_panel,
)

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

def main():
    parser = argparse.ArgumentParser(description="全国どこでもGSM/MSM局地天気図パネル生成スクリプト")
    parser.add_argument("--model", choices=["gsm", "msm"], default="gsm", help="モデル選択 (gsm or msm)")
    parser.add_argument("--city", required=True, help="地名（例：長岡花火）")
    parser.add_argument("--pin_lat", type=float, required=True, help="ピンポイント緯度")
    parser.add_argument("--pin_lon", type=float, required=True, help="ピンポイント経度")
    parser.add_argument("--lat_range", type=float, nargs=2, required=True, help="地図範囲の緯度 [min max]")
    parser.add_argument("--lon_range", type=float, nargs=2, required=True, help="地図範囲の経度 [min max]")
    parser.add_argument("--output", type=str, default=None, help="保存ファイル名（省略可）")
    parser.add_argument("--ncols", type=int, default=12, help="パネルの横列数（予報時刻数）")
    parser.add_argument("--nrows", type=int, default=6, help="パネルの縦行数（固定6）")
    args = parser.parse_args()

    BASE_DIR = "./data"
    NCOLS = args.ncols
    NROWS = args.nrows
    OUTFILE = args.output or f"{args.city}_local_{args.model}_map.jpg"

    # === モデル別に描画関数とパターン設定 ===
    if args.model == "gsm":
        from module.gpv_plotter_gsm import (
            plot_emagram_gsm_panel,
            plot_700hpa_dindex_500hpa_temp_gsm,
            plot_850hpa_temp_wind_700hpa_w_gsm,
            plot_850hpa_thetae_stream_gsm,
            plot_925hpa_temp_wind_dindex_gsm,
            plot_surface_pressure_and_wind_gsm,
        )
        PATTERNS = GSM_PATTERNS
        plot_func_list = [
            plot_emagram_gsm_panel,
            plot_700hpa_dindex_500hpa_temp_gsm,
            plot_850hpa_temp_wind_700hpa_w_gsm,
            plot_850hpa_thetae_stream_gsm,
            plot_925hpa_temp_wind_dindex_gsm,
            plot_surface_pressure_and_wind_gsm,
        ]
    else:
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

    try:
        print(f"=== {args.model.upper()}ローカルパネル生成開始：{args.city} ===")

        if args.model == "gsm":
            # GSMは従来方式
            init_dt = find_existing_init_dt(PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 6, 12, 18])
            if init_dt is None:
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                print("【ERROR】GSM GPVファイル未取得。NO DATAパネル送信")
                sys.exit(0)

            panel_files = download_gpv_panel(PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
            pattern_files = [f for f in panel_files if f and len(f) == len(PATTERNS)]
            if not pattern_files or len(pattern_files) < 3:
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
            file_list = [item for sublist in pattern_files for item in sublist]
            nc_paths = []
            for path, _ in file_list:
                nc_path = grib2_to_nc(path)
                if nc_path and os.path.exists(nc_path):
                    nc_paths.append(nc_path)
            ds_list = [xr.open_dataset(nc) for nc in nc_paths if os.path.exists(nc)]
            if not ds_list or len(ds_list) < 3:
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
            ds_list_aligned = align_datasets_common(ds_list)
            ds = xr.merge(ds_list_aligned, compat="override", join="outer")
            times = ds.time.values[:NCOLS]

        else:
            # MSMはindex.htmlパースDL（どちらか単独でもOK）
            BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
            YMD = pd.Timestamp.now().strftime("%Y%m%d")
            files = find_existing_msm_files(BASE_URL, YMD)
            if not files:
                print("NO DATA: MSMサーバにファイルが見つかりません")
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
            latest_init = max([f["init"] for f in files])
            use_files = [f for f in files if f["init"] == latest_init][:NCOLS]
            if not use_files or len(use_files) < 2:
                print("NO DATA: 有効ファイル不足")
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
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
            if not nc_paths:
                print("NO DATA: NetCDF変換失敗")
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
            ds_list = []
            for nc in nc_paths:
                try:
                    ds = xr.open_dataset(nc)
                    ds_list.append(ds)
                except Exception as e:
                    print(f"[WARN] open_dataset失敗: {nc} ({e})")
            if not ds_list:
                print("NO DATA: Dataset不足")
                times = get_gpv_nodata_times(NCOLS)
                make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
                sys.exit(0)
            ds = align_datasets_common(ds_list, ncols=NCOLS)
            times = ds.time.values[:NCOLS] if hasattr(ds, "time") else get_gpv_nodata_times(NCOLS)

        # --- パネル描画 ---
        make_local_weather_panel(
            ds, times, OUTFILE,
            pin_lat=args.pin_lat, pin_lon=args.pin_lon, city_name=args.city,
            lat_range=tuple(args.lat_range), lon_range=tuple(args.lon_range),
            plot_func_list=plot_func_list,
            nrows=NROWS, ncols=NCOLS,
        )
        print("画像生成完了\n=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        times = get_gpv_nodata_times(NCOLS)
        make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
        sys.exit(1)

if __name__ == "__main__":
    main()
