# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（GRIB2直接読取 cfgrib対応版）
# 2025-06-22 改訂 by ChatGPT
# ===============================================

import sys
import os
import traceback
import pandas as pd
import xarray as xr

from gpv_downloader import (
    download_gpv_panel,
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
    init_dt = pd.Timestamp.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [init_dt + pd.Timedelta(hours=3*i) for i in range(ncols)]

if __name__ == "__main__":
    try:
        print("=== GSMパネル自動生成（GRIB2ダイレクト） ===")
        # 1. イニシャル時刻決定（例: 最新の0/12UTC）
        init_dt = pd.Timestamp.now().replace(hour=0, minute=0, second=0, microsecond=0)
        print(f"[INFO] init_dt: {init_dt}")

        # 2. GRIB2ファイル自動DL（パネル分すべて）
        panel_files = download_gpv_panel(
            GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS
        )

        # 3. 欠損・異常・Noneを除去し、2パターン揃った時刻のみ抽出
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

        # 4. GRIB2→xarray Datasetリスト取得（NetCDF不要！）
        ds_list = []
        for files in pattern_files:
            sub_ds_list = []
            for path, t in files:
                try:
                    ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
                    sub_ds_list.append(ds)
                except Exception as e:
                    print(f"[SKIP] GRIB2 open失敗: {path} ({e})")
            # 複数パターンをmerge
            if len(sub_ds_list) == len(GSM_PATTERNS):
                ds_merged = xr.merge(sub_ds_list, compat="override", join="outer")
                ds_list.append(ds_merged)
        if not ds_list or len(ds_list) < 2:
            print("[NO DATA] ds_list少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 5. パネル描画
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.concat(ds_list_aligned, dim="time")  # 時系列で結合
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]
        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("[OK] 画像生成完了:", OUTFILE)
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
