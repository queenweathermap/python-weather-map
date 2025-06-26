# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意地点GSM/MSM局地天気図パネル（エマグラム付き）生成スクリプト
# 2025-06-27 ChatGPT（module/core/plot対応リファクタ）
# ===============================================================

import sys
import traceback
import argparse
import os
import pandas as pd
import xarray as xr

from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.core.gpv_converter import grib2_to_netcdf
from module.core.gpv_data_loader import load_dataset
from module.panel_utils import (
    make_nodata_weather_panel,
    align_datasets_common,
    make_local_weather_panel,
)

DEFAULT_RANGE_WIDTH = 2.5

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
    OUTFILE = args.output or f"{args.city}_local_{args.model}_map.jpg"

    # === モデル別に描画関数とパターン設定 ===
    if args.mo
