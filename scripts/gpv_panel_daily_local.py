# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意地点GSM/MSM局地天気図パネル（エマグラム付き）生成スクリプト
# 2025-06-27 ChatGPT（module/core/plot対応リファクタ）
# ===============================================================

import os
import sys
import traceback
import argparse
import pandas as pd
import xarray as xr


from dotenv import load_dotenv
from module.utils.slack_utils import send_slack_message
from module.utils.drive_utils import upload_to_drive
from module.panel_utils import make_local_weather_panel

from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.core.gpv_converter import grib2_to_netcdf
from module.core.gpv_data_loader import load_dataset
from module.panel_utils import (
    make_nodata_weather_panel,
    align_datasets_common,
    make_local_weather_panel,
)

DEFAULT_RANGE_WIDTH = 2.5


# .env自動読込
load_dotenv()

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

def parse_args():
    parser = argparse.ArgumentParser(description="中心座標だけで任意地点天気パネルを描画")
    parser.add_argument("--model", choices=["gsm", "msm"], default="gsm", help="モデル選択 (gsm or msm)")
    parser.add_argument("--city", required=True, help="地名（例：長岡花火）")
    parser.add_argument("--pin_lat", type=float, required=True, help="中心緯度（例：37.4462）")
    parser.add_argument("--pin_lon", type=float, required=True, help="中心経度（例：138.8521）")
    parser.add_argument("--range_width", type=float, default=DEFAULT_RANGE_WIDTH, help="範囲半径（度, デフォルト2.5）")
    parser.add_argument("--output", type=str, default=None, help="保存ファイル名（省略可）")
    parser.add_argument("--ncols", type=int, default=12, help="パネル横列数（予報時刻数）")
    parser.add_argument("--nrows", type=int, default=6, help="パネル縦行数（固定6）")
    args = parser.parse_args()
    args.lat_min = args.pin_lat - args.range_width
    args.lat_max = args.pin_lat + args.range_width
    args.lon_min = args.pin_lon - args.range_width
    args.lon_max = args.pin_lon + args.range_width
    print(f"【描画パネル】地名: {args.city}")
    print(f"中心緯度経度: ({args.pin_lat}, {args.pin_lon})")
    print(f"範囲: lat {args.lat_min:.3f}～{args.lat_max:.3f}, lon {args.lon_min:.3f}～{args.lon_max:.3f}")
    return args

def main():
    args = parse_args()
    BASE_DIR = "./data"
    NCOLS = args.ncols
    NROWS = args.nrows
    OUTFILE = args.output or f"{args.city}_{args.model}_panel.jpg"

    # === モデル別に描画関数とパターン設定 ===
    if args.model == "gsm":
        from module.plot.plot_emagram import plot_emagram_gsm_panel
        from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_gsm
        from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_gsm
        from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream_gsm
        from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_gsm
        from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_gsm
        PATTERNS = MODEL_CONFIG["GSM"]["patterns"]
        plot_func_list = [
            plot_emagram_gsm_panel,
            plot_700hpa_dindex_500hpa_temp_gsm,
            plot_850hpa_temp_wind_700hpa_w_gsm,
            plot_850hpa_thetae_stream_gsm,
            plot_925hpa_temp_wind_dindex_gsm,
            plot_surface_pressure_and_wind_gsm,
        ]
    else:
        from module.plot.plot_emagram import plot_emagram_msm_panel
        from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_msm
        from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_msm
        from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream_msm
        from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_msm
        from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm
        PATTERNS = MODEL_CONFIG["MSM"]["patterns"]
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
        # --- データ取得・処理 ---
        dt_now = pd.Timestamp.now()
        init_dt = dt_now.replace(minute=0, second=0, microsecond=0)
        panel_files = download_gpv_panel(PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        file_list = [item for sublist in panel_files if sublist for item in sublist if item]
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_netcdf(path, path.replace(".bin", ".nc"))
            if nc_path:
                nc_paths.append(nc_path)
        ds_list = [load_dataset(nc) for nc in nc_paths if os.path.exists(nc)]
        if not ds_list or len(ds_list) < 2:
            times = get_gpv_nodata_times(NCOLS)
            make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
            print("【ERROR】GPVファイル未取得。NO DATAパネル送信")
            sys.exit(0)
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = ds.time.values[:NCOLS] if hasattr(ds, "time") else get_gpv_nodata_times(NCOLS)

        # --- パネル描画 ---
        make_local_weather_panel(
            ds, times, OUTFILE,
            pin_lat=args.pin_lat, pin_lon=args.pin_lon, city_name=args.city,
            lat_range=(args.lat_min, args.lat_max), lon_range=(args.lon_min, args.lon_max),
            plot_func_list=plot_func_list,
            nrows=NROWS, ncols=NCOLS,
        )
        print("画像生成完了\n=== 完了 ===")
    
        # --- Driveアップ & Slack通知 ---
        drive_url = upload_to_drive(os.path.join("./data", OUTFILE))
        send_slack_message(f"【自動配信】{args.city} {args.model.upper()} パネル\n{drive_url}")
    
        print("[OK] ローカル天気図・Drive・Slack連携 完了")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        times = get_gpv_nodata_times(NCOLS)
        make_nodata_weather_panel(times, OUTFILE, city_name=args.city)
        sys.exit(1)

if __name__ == "__main__":
    main()
