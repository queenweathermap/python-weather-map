# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（12時刻×2パターン/日パネル）
# -----------------------------------------------
# 必須: gpv_downloader.py, make_nodata_weather_panel など
# 2025-06-13 by ChatGPT
# ===============================================

import sys
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import (
    find_nearest_init, download_gpv_panel,
    grib2_to_nc, GSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import make_nodata_weather_panel, make_daily_weather_panel_multi_time, align_datasets_common

BASE_DIR = "./data"
NCOLS = 12

if __name__ == "__main__":
    try:
        print("1. データダウンロード開始")
        # 直近のイニシャル時刻を取得（UTC 12, 0, 18, 6 優先）
        init_dt = find_nearest_init()  # ←引数なし
        print(f"init_dt: {init_dt}")

        # データダウンロード（pattern_files: [ [(path1,時刻), (path2,時刻)], ...] ）
        panel_files = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        # 使うべきファイルセットを抽出
        # → 1時刻分のパターンペア取得セット
        pattern_files = [f for f in panel_files if len(f) == len(GSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, "gsm_panel_nodata.jpg")
            print("【ERROR】GPVファイル未取得。NO DATAパネル送信処理へ…")
            sys.exit(1)

        print("2. NetCDF変換開始")
        # ファイルセットを1つにflatten
        file_list = [item for sublist in pattern_files[:2] for item in sublist]
        nc_paths = [grib2_to_nc(path) for path, _ in file_list]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        # --- 各ファイルの中身を詳細print
        for i, ds in enumerate(ds_list):
            print(f"--- ds_list[{i}] ---")
            print(ds)
            print("dims:", ds.dims)
            print("coords:", list(ds.coords))
            print("variables:", list(ds.variables))
            if "time" in ds.coords:
                print("time:", ds["time"].values)
                print("time dtype:", ds["time"].dtype)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("\n== merge前のds_listチェック完了 ==\n")

        # --- timeのdtypeを明示的に統一
        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds
                print(f"[修正] ds_list[{i}]のtimeをdatetime64[ns]に揃えました")

        # --- merge (join="outer"を明示)
        ds_list_aligned = align_datasets_common(ds_list)
        for i, ds in enumerate(ds_list_aligned):
            print(f"--- ds_list_aligned[{i}] ---")
            print(ds)
            print("dims:", ds.dims)
            print("coords:", list(ds.coords))
            print("variables:", list(ds.variables))
            if "time" in ds.coords:
                print("time:", ds["time"].values)
                print("time dtype:", ds["time"].dtype)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("== align_datasets_common OK ==")

        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        print("xr.merge OK")
        print(ds)
        print("ds.data_vars:", ds.data_vars)
        print("ds.variables:", list(ds.variables))
        print("ds.time dtype:", ds.time.dtype)
        print("ds.time.values:", ds.time.values)
        print("len(ds.time):", len(ds.time.values))

        # --- times取得（上位12件/空チェック）
        times = ds.time.values[:NCOLS]
        print("times:", times)

        # --- パネル作成
        make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
