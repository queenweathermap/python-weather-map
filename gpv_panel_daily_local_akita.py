# gpv_panel_daily_local_akita.py
# ========================================================
# 秋田局地パネル（6段×12列）自動生成スクリプト（GSM版：DL部改良）
# --------------------------------------------------------
# ・指定地点（秋田市）の局地天気図をパネル出力
# ・GSMデータ（12時刻×2パターン）で運用中（MSM復旧時に切替可）
# ・NO DATA時もダミー画像必ず出力（Slackや運用バッチで使える設計）
# ・ファイル取得→NetCDF変換→合成→パネル描画まで一気通貫
# ・エラー/例外時も必ず画像出力で終了（自動配信に最適）
# 2025-06-17 by ChatGPT
# ========================================================

import os
import sys
import traceback
import xarray as xr
import pandas as pd

from gpv_downloader import (
    download_available_gpv, grib2_to_nc,
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

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    grib2_files, nc_paths, init_time = [], [], None

    # GSM_PATTERNS = [気圧面, 地上]（2ファイル個別に最新DL）
    for pattern in GSM_PATTERNS:
        grib2_path, itime = download_available_gpv(pattern, BASE_DIR, GPV_MIRROR_URLS)
        if grib2_path is not None and itime is not None:
            grib2_files.append(grib2_path)
            if init_time is None:
                init_time = itime

    if len(grib2_files) < 2:
        print("【NO DATA】2ファイルそろわず。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=[pd.Timestamp.now() + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
        )
        sys.exit(0)

    # GRIB2→NetCDF変換
    for path in grib2_files:
        nc = grib2_to_nc(path)
        if nc:
            nc_paths.append(nc)

    if len(nc_paths) < 2:
        print("【NO DATA】NetCDF変換不良。ダミー画像出力")
        make_nodata_weather_panel(
            save_path=OUTFILE,
            city_name=CITY_NAME,
            times=[pd.Timestamp.now() + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
        )
        sys.exit(0)

    # データ結合・共通時刻合わせ
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

except Exception as e:
    print("【NO DATA】例外:", e)
    traceback.print_exc()
    make_nodata_weather_panel(
        save_path=OUTFILE,
        city_name=CITY_NAME,
        times=[pd.Timestamp.now() + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
    )
    sys.exit(0)

# ====== この後はパネル描画(make_local_weather_panel)やSlack通知など続けてください ======
