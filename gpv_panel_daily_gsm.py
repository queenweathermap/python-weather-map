# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（12時刻×2パターン/日パネル・ハードコード検証版）
# -----------------------------------------------
# 2025-06-19 by ChatGPT
# ===============================================

import sys
import os
import traceback
import pandas as pd
import xarray as xr
from pathlib import Path

from gpv_downloader import (
    download_gpv_panel, grib2_to_nc,
    GSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "gsm_weather_map.jpg"

def get_gpv_nodata_times(ncols=12):
    # 画像には検証日付に揃えるのが親切
    init_dt = pd.Timestamp("2024-06-20 00:00:00")
    return [init_dt + pd.Timedelta(hours=3*i) for i in range(ncols)]

if __name__ == "__main__":
    try:
        print("=== GSMパネル自動生成【ハードコード版】===")
        # ---------------------------
        # 1. ハードコードされたinit_dtでDLを試行
        # ---------------------------
        init_dt = pd.Timestamp("2024-06-20 00:00:00")
        print(f"[INFO] ハードコードinit_dt: {init_dt}")
        panel_files = download_gpv_panel(
            GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS
        )
        # 欠損時刻・異常型を除去し、2パターン揃った時刻のみ抽出
        pattern_files = []
        for i, f in enumerate(panel_files):
            if isinstance(f, (list, tuple)) and len(f) == len(GSM_PATTERNS):
                if None not in f:
                    pattern_files.append(f)
                else:
                    print(f"[WARN] panel_files[{i}]にNoneあり: {f}")
            else:
                print(f"[WARN] panel_files[{i}]が異常: {f}")
        if not pattern_files or len(pattern_files) < 2:
            print("[NO DATA] 2層揃う時刻が見つからず。ダミーパネル生成")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # flatten
        file_list = [item for sublist in pattern_files for item in sublist]

        # ---------------------------
        # 2. GRIB2→NetCDF変換
        # ---------------------------
        nc_paths = []
        for path, t in file_list:
            nc_path = grib2_to_nc(path)
            if nc_path and os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}（元ファイル: {path}）")
        if not nc_paths or len(nc_paths) < 2:
            print("[NO DATA] ncファイル少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # ---------------------------
        # 3. xarray Datasetリスト取得・merge
        # ---------------------------
        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 2:
            print("[NO DATA] ds_list少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # アラインしてmerge
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")

        # 描画対象時刻抽出（最大12コマ）
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        # ---------------------------
        # 4. パネル画像描画
        # ---------------------------
        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("[OK] 画像生成完了:", OUTFILE)
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
