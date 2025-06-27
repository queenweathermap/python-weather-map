# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意地点GSM/MSM局地天気図パネル（エマグラム付き）生成＋ZIP化＋Drive/Slack通知
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
from module.utils.zip_utils import zip_files
from module.panel_utils import (
    make_nodata_weather_panel,
    align_datasets_common,
    make_local_weather_panel,
)
from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.core.gpv_converter import grib2_to_netcdf
from module.core.gpv_data_loader import load_dataset

DEFAULT_RANGE_WIDTH = 2.5

load_dotenv()  # .env自動読込

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

def parse_args():
    parser = argparse.ArgumentParser(description="中心座標だけで任意地点天気パネルを描画")
    parser.add_argument("--model", choices=["gsm", "msm"], default="gsm")
    parser.add_argument("--city", required=True)
    parser.add_argument("--pin_lat", type=float, required=True)
    parser.add_argument("--pin_lon", type=float, required=True)
    parser.add_argument("--range_width", type=float, default=DEFAULT_RANGE_WIDTH)
    parser.add_argument("--output_prefix", type=str, default=None)
    parser.add_argument("--ncols", type=int, default=12)
    parser.add_argument("--nrows", type=int, default=6)
    parser.add_argument("--npages", type=int, default=1)
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
    NPAGES = args.npages
    OUT_PREFIX = args.output_prefix or f"{args.city}_{args.model}_panel"
    panel_imgs = []

    # モデル別処理（省略、元のまま）

    try:
        print(f"=== {args.model.upper()}ローカルパネル生成開始：{args.city} ===")
        # データ取得・処理（元通り）

        # 例: 1ページにつきNCOLS列×NROWS行ずつ、ページ分割
        for page in range(NPAGES):
            out_img = f"{OUT_PREFIX}_p{page+1}.jpg"
            # times/データもページ分割（ここはmake_local_weather_panel等の修正が必要）
            # ↓下記はサンプル、実際はページごとにtimes等も分割
            make_local_weather_panel(
                ds, times, out_img,
                pin_lat=args.pin_lat, pin_lon=args.pin_lon, city_name=args.city,
                lat_range=(args.lat_min, args.lat_max), lon_range=(args.lon_min, args.lon_max),
                plot_func_list=plot_func_list,
                nrows=NROWS, ncols=NCOLS,
            )
            panel_imgs.append(os.path.join(BASE_DIR, out_img))

        # --- まとめてZIP ---
        zip_path = os.path.join(BASE_DIR, f"{OUT_PREFIX}.zip")
        zip_files(panel_imgs, zip_path)

        # --- Driveアップ & Slack通知 ---
        drive_url = upload_to_drive(zip_path)
        send_slack_message(f"【自動配信】{args.city} {args.model.upper()} パネル（ZIP）\n{drive_url}")
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
