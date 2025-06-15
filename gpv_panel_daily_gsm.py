# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（12時刻×2パターン/日パネル）
# ・ダウンロード/変換失敗時はNO DATAパネルを強制出力
# ・NoneチェックとNO DATA用の時刻リストを必ず渡す
# ===============================================

import sys
import traceback
import os
import xarray as xr
import pandas as pd

from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
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

def get_nodata_times():
    """NO DATAパネル用に等間隔の時刻リストを返す"""
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    return [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]

if __name__ == "__main__":
    try:
        print("=== GSMパネル処理開始 ===")
        # 最新init時刻取得
        init_dt = find_existing_init_dt(GSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 12])
        if init_dt is None:
            print("NO DATA: GSMファイルがサーバに見つかりません")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        print(f"init_dt: {init_dt}")
        panel_files = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        # 空でない時刻だけ抜き出す
        pattern_files = [f for f in panel_files if f and len(f) == len(GSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            make_daily_weather_panel_multi_time(ds, times, OUTFILE)
            sys.exit(0)

        print("2. NetCDF変換開始")
        # 存在する時刻だけフラット化
        file_list = [item for sublist in pattern_files for item in sublist]
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_nc(path)
            if nc_path and os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        print("nc_paths:", nc_paths)

        if not nc_paths or len(nc_paths) < 2:
            print("NO DATA: ncファイル少なすぎ")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 2:
            print("NO DATA: ds_list少なすぎ")
            make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        # timeはnp.datetime64配列なのでpandas.Timestamp化
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
