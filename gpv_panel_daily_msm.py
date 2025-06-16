# gpv_panel_daily_msm.py
# ========================================================
# MSMパネル自動生成スクリプト（6行×12列パネル・全国域MSM用）
# --------------------------------------------------------
# ・気象庁GPV MSMデータを自動DL・NetCDF変換・合成・パネル出力
# ・直近の利用可能イニシャル時刻から12時刻（3時間毎）を取得
# ・NO DATA時も必ずパネル画像出力（Slack自動配信/監視用途にも最適）
# ・エラー時もNO DATA画像を確実に生成し異常を通知
# --------------------------------------------------------
# 2025-06-17 by ChatGPT
# ========================================================

import sys
import traceback
import os
import pandas as pd
import xarray as xr

from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    MSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

# MSM_PATTERNS を局地・全国で分離も可
MSM_LOCAL_PATTERNS = [
    "MSM_GPV_Rjp_L-pall",
    "MSM_GPV_Rjp_Lsurf"
]
MSM_NATIONAL_PATTERNS = [
    "MSM_GPV_Gll0p1deg_L-pall",
    "MSM_GPV_Gll0p1deg_Lsurf"
]


BASE_DIR = "./data"
NCOLS = 12
OUTFILE = "msm_weather_map.jpg"

def get_nodata_times():
    """NO DATAパネル用に等間隔の時刻リストを返す"""
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    return [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]

if __name__ == "__main__":
    try:
        print("=== MSMパネル処理開始 ===")
        # 1. 最新の利用可能イニシャル時刻（例: 0, 3, ..., 21JST）を取得
        init_dt = find_existing_init_dt(MSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 3, 6, 9, 12, 15, 18, 21])
        print(f"init_dt: {init_dt}")
        if init_dt is None:
            print("NO DATA: MSMファイルがサーバに見つかりません")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 2. パターンファイルDL（分割MSMパネル取得）
        panel_files = download_gpv_panel(MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        # 3. すべてのパターン揃った時刻だけ抜き出す
        pattern_files = [f for f in panel_files if f and len(f) == len(MSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 3:
            print("NO DATA: pattern_files is None or <3")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 4. NetCDF変換
        print("2. NetCDF変換開始")
        file_list = [item for sublist in pattern_files for item in sublist]
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_nc(path)
            if nc_path and os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        print("nc_paths:", nc_paths)

        if not nc_paths or len(nc_paths) < 3:
            print("NO DATA: ncファイル少なすぎ")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 5. xarrayで全NetCDFを合成・整列
        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 3:
            print("NO DATA: ds_list少なすぎ")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        # 6. パネル描画
        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
