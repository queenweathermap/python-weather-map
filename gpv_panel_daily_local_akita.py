# gpv_panel_daily_msm_akita.py
# ========================================================
# 秋田局地パネル（6段×12列）自動生成スクリプト
# --------------------------------------------------------
# ・指定地点（秋田市）の局地天気図をパネル出力
# ・GSMデータ（12時刻×2パターン）で運用中（MSM復旧時に切替可）
# ・NO DATA時もダミー画像必ず出力（Slackや運用バッチで使える設計）
# ・ファイル取得→NetCDF変換→合成→パネル描画まで一気通貫
# ・エラー/例外時も必ず画像出力で終了（自動配信に最適）
# --------------------------------------------------------
# 2025-06-17 by ChatGPT
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    GSM_PATTERNS, GPV_MIRROR_URLS
)
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "akita_local_msm_map.jpg"

# 秋田市（ピンポイント座標・地名）
PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

if __name__ == "__main__":
    try:
        print("=== 秋田局地パネル処理開始 ===")
        # ---- 1. 最新のGSMイニシャル時刻を取得（例：0, 12JST） ----
        init_dt = find_existing_init_dt(GSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 12])
        print("GSM最新イニシャル時刻:", init_dt)
        if init_dt is None:
            print("NO DATA: GSMファイルがサーバに見つかりません")
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        # ---- 2. 各時刻ファイルDL・存在チェック ----
        panel_files = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        pattern_files = [f for f in panel_files if f and len(f) == len(GSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        # ---- 3. GRIB2→NetCDF変換 ----
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

        if not nc_paths or len(nc_paths) < 2:
            print("NO DATA: ncファイル少なすぎ")
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        # ---- 4. xarrayで全NetCDFをマージ ----
        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 2:
            print("NO DATA: ds_list少なすぎ")
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        # ---- 5. パネル描画 ----
        make_local_weather_panel(
            ds, times, OUTFILE,
            pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME
        )
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        # 例外時も必ずNO DATA画像を出力して終了
        now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [now + pd.Timedelta(hours=3 * i) for i in range(NCOLS)]
        make_nodata_weather_panel(times, save_path=OUTFILE)
        sys.exit(1)
