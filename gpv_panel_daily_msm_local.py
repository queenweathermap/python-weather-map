# gpv_panel_daily_msm_local.py
# ===============================================================
# 任意の地点でMSM局地天気図パネル（エマグラム付き）を生成する汎用スクリプト
# ----------------------------------------------------------------
# ・全国どこでも「ピンポイント＋周辺範囲」で局地パネルを自動生成
# ・地名・緯度経度・範囲・出力ファイル名はコマンドライン引数で指定
# ・観測地点やイベント会場など日々異なる任意地点でのパネル作成に最適
# ・GSM/MSM定時運用パネル（秋田局地など）とは独立して個別出力
# ・ワークフロー・バッチ処理・スポット出力に柔軟対応！
# ----------------------------------------------------------------
# 実行例:
#   python gpv_panel_daily_msm_local.py --city "長岡花火" --pin_lat 37.444 --pin_lon 138.848 \
#       --lat_range 37.3 37.6 --lon_range 138.7 139.1 --output nagoka_panel.jpg
#
# コマンドライン引数:
#   --city       : 地名（タイトル等に使用）
#   --pin_lat    : ピンポイント緯度（エマグラム中心位置）
#   --pin_lon    : ピンポイント経度
#   --lat_range  : 地図描画の緯度範囲（2つ、例 37.3 37.6）
#   --lon_range  : 地図描画の経度範囲（2つ、例 138.7 139.1）
#   --output     : 保存ファイル名（省略可／自動命名）
#
# 必須: gpv_downloader.py, panel_utils.py, gpv_plotter_msm.py
# 2025-06-13 by ChatGPT
# ===============================================================

import sys
import traceback
import argparse
import pandas as pd
import xarray as xr

from gpv_downloader import (
    download_gpv_panel, grib2_to_nc, find_nearest_init,
    GPV_MIRROR_URLS, MSM_PATTERNS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    align_datasets_common,
    make_local_weather_panel,
)
from module.gpv_plotter_msm import (
    plot_emagram_msm_panel,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)

# ===============================================
# メイン処理
# ===============================================
def main():
    parser = argparse.ArgumentParser(
        description="全国どこでもMSM局地天気図パネル生成スクリプト"
    )
    parser.add_argument("--city", required=True, help="地名（例：長岡花火）")
    parser.add_argument("--pin_lat", type=float, required=True, help="ピンポイント緯度")
    parser.add_argument("--pin_lon", type=float, required=True, help="ピンポイント経度")
    parser.add_argument("--lat_range", type=float, nargs=2, required=True, help="地図範囲の緯度 [min max]")
    parser.add_argument("--lon_range", type=float, nargs=2, required=True, help="地図範囲の経度 [min max]")
    parser.add_argument("--output", type=str, default=None, help="保存ファイル名（省略可）")
    parser.add_argument("--ncols", type=int, default=12, help="パネルの横列数（予報時刻数）")
    parser.add_argument("--nrows", type=int, default=6, help="パネルの縦行数（固定6）")
    args = parser.parse_args()

    # 主要な入力値に空欄やNone/0/""があれば何もせず正常終了
    if not args.city or not args.pin_lat or not args.pin_lon or not args.lat_range or not args.lon_range:
        print("[INFO] 必須パラメータが空欄。ローカルパネル生成はスキップします。")
        sys.exit(0)

    BASE_DIR = "./data"
    NCOLS = args.ncols
    NROWS = args.nrows

    try:
        print(f"=== MSMローカルパネル生成開始：{args.city} ===")
        print(f"ピンポイント: ({args.pin_lat}, {args.pin_lon})  範囲: lat{args.lat_range}, lon{args.lon_range}")
        # 直近のイニシャル時刻取得（JSTで最も近い00/06/12/18UTC）
        init_dt = find_nearest_init()
        print(f"init_dt: {init_dt}")

        # MSM GPVデータ一括DL（ncols本分）
        panel_files = download_gpv_panel(
            MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS
        )
        print("panel_files:", panel_files)

        # パターンすべてそろった時刻のみ採用
        pattern_files = [f for f in panel_files if len(f) == len(MSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 3:
            print("NO DATA: pattern_files is None or <3")
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, args.output or "local_panel_nodata.jpg")
            print("【ERROR】GPVファイル未取得。NO DATAパネル送信処理へ…")
            sys.exit(0)  # ← ここを0に

        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files[:3] for item in sublist]
        nc_paths = [grib2_to_nc(path) for path, _ in file_list]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        # time dtype 統一
        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds
                print(f"[修正] ds_list[{i}]のtimeをdatetime64[ns]に揃えました")

        # 共通部分でalign
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        print("xr.merge OK")
        print("ds.time.values:", ds.time.values)
        print("len(ds.time):", len(ds.time.values))

        # 上位ncols時刻だけ抜き出し
        if len(ds.time) == 0:
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, args.output or "local_panel_nodata.jpg")
            print("【ERROR】MSM GPVに有効データ無し。NO DATAパネル生成")
            sys.exit(0)  # ← ここも0に
        times = ds.time.values[:NCOLS]
        print("times:", times)

        # パネル作成
        make_local_weather_panel(
            ds, times, args.output or f"{args.city}_local_msm_map.jpg",
            pin_lat=args.pin_lat, pin_lon=args.pin_lon, city_name=args.city,
            lat_range=tuple(args.lat_range), lon_range=tuple(args.lon_range),
            plot_func_list=[
                plot_emagram_msm_panel,
                plot_700hpa_dindex_500hpa_temp_msm,
                plot_850hpa_temp_wind_700hpa_w_msm,
                plot_850hpa_thetae_stream_msm,
                plot_925hpa_temp_wind_dindex_msm,
                plot_surface_pressure_and_wind_msm,
            ],
            nrows=NROWS, ncols=NCOLS,
        )
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)

# ===============================================
if __name__ == "__main__":
    main()
