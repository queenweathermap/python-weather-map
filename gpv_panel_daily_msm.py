# gpv_panel_daily_msm.py
# ========================================================
# MSMパネル自動生成スクリプト（全国域・12時刻×2パターン）
# --------------------------------------------------------
# MSM GPVデータ（L-pall/Lsurfいずれか単独でもOK）を自動DL
# 欠損時はNO DATAパネル生成で自動継続
# 2025-06-19 by ChatGPT
# ========================================================

import sys
import traceback
import os
import xarray as xr
import pandas as pd

from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    MSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "msm_weather_map.jpg"

def get_gpv_nodata_times(ncols=12):
    """
    MSM NO DATA時刻リスト生成（GSMと同じロジックでOK）
    """
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    if hour < 0:
        base_time -= pd.Timedelta(days=1)
        base_time = base_time.replace(hour=18)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

if __name__ == "__main__":
    try:
        print("=== MSMパネル処理開始 ===")
        # 1. 最新イニシャル時刻を探索（GSM/NOAA同様、0/12UTC中心）
        init_dt = find_existing_init_dt(
            MSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 12]
        )
        if init_dt is None:
            print("NO DATA: MSMファイルがサーバに見つかりません")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)
        print(f"init_dt: {init_dt}")

        # 2. 12時刻×2パターン自動DL
        panel_files = download_gpv_panel(
            MSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS
        )
        print("panel_files:", panel_files)

        # 3. 欠損・異常・Noneを除去し、2パターン揃った時刻のみ抽出
        pattern_files = []
        for i, f in enumerate(panel_files):
            if isinstance(f, (list, tuple)) and len(f) == len(MSM_PATTERNS):
                if None not in f:
                    pattern_files.append(f)
                else:
                    print(f"[WARN] panel_files[{i}]にNoneあり: {f}")
            else:
                print(f"[WARN] panel_files[{i}]が異常: {f}")
        print("pattern_files:", pattern_files)

        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # flatten時もNoneが来ないようにガード
        file_list = []
        for sublist in pattern_files:
            if isinstance(sublist, (list, tuple)):
                for item in sublist:
                    if item is not None:
                        file_list.append(item)
                    else:
                        print("[WARN] sublist内itemがNone:", sublist)

        print("2. NetCDF変換開始")
        # 4. GRIB2→NetCDF変換（全ファイル一括処理）
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_nc(path)
            if nc_path and os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}（元ファイル: {path}）")
        print("nc_paths:", nc_paths)

        if not nc_paths or len(nc_paths) < 2:
            print("NO DATA: ncファイル少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 5. NetCDF→xarray Datasetリスト
        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 2:
            print("NO DATA: ds_list少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 6. 共通座標アライン＆合成
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]
        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
