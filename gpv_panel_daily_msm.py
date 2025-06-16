# gpv_panel_daily_msm.py
# ========================================================
# MSMパネル自動生成スクリプト（6行×12列パネル・全国域MSM用/HTMLパースDL）
# --------------------------------------------------------
# ・MSM GPVデータ（L-pall/Lsurf各FH帯ペア）をサーバindex.htmlパースで全自動DL
# ・揃ったペアのみNetCDF変換・合成・パネル出力
# ・NO DATA時も必ず画像出力（Slack/監視運用にも最適）
# ・エラー時もNO DATA画像を必ず生成し異常通知
# --------------------------------------------------------
# 2025-06-18 by ChatGPT
# ========================================================

import os
import sys
import traceback
import pandas as pd
import xarray as xr

from module.utils.gpv_html_parser import find_existing_msm_pairs
from gpv_downloader import grib2_to_nc
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

# ========================================
# 設定
# ========================================
BASE_DIR = "./data"
OUTFILE = "msm_weather_map.jpg"
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
YMD = pd.Timestamp.now().strftime("%Y%m%d")
NCOLS = 12

def get_nodata_times(ncols=NCOLS):
    """NO DATAパネル用に等間隔の時刻リストを返す"""
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    return [now + pd.Timedelta(hours=3 * i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)

    print("=== MSMパネル自動処理（HTMLパースDL）開始 ===")
    # 1. サーバindex.htmlから最新のL-pall/Lsurfペア（全国MSM）を抽出
    pairs = find_existing_msm_pairs(BASE_URL, YMD)
    if not pairs:
        print("NO DATA: サーバ上にペアが見つかりません")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    # 2. 一番新しいinit時刻のものから最大NCOLS個だけ利用
    latest_init = max([p[2] for p in pairs])
    use_pairs = [p for p in pairs if p[2] == latest_init][:NCOLS]
    if len(use_pairs) < 2:
        print("NO DATA: 有効ペア不足")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    # 3. ペアごとにGRIB2→NetCDF変換
    nc_paths = []
    for l_pall_path, lsurf_path, init_time, fh_band in use_pairs:
        nc1 = grib2_to_nc(l_pall_path)
        nc2 = grib2_to_nc(lsurf_path)
        if nc1 and nc2:
            nc_paths.extend([nc1, nc2])
    if len(nc_paths) < 2:
        print("NO DATA: NetCDF変換失敗")
        make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
        sys.exit(0)

    # 4. NetCDFをxarrayで合成・座標整列
    ds_l_pall = xr.open_dataset([p for p in nc_paths if "L-pall" in p][0])
    ds_lsurf  = xr.open_dataset([p for p in nc_paths if "Lsurf" in p][0])
    ds = xr.merge([ds_l_pall, ds_lsurf])
    ds = align_datasets_common(ds, ncols=NCOLS)

    # 5. 描画用時刻リスト
    times = ds.time.values[:NCOLS]

    # 6. パネル描画
    make_daily_weather_panel_multi_time(ds, times, OUTFILE)
    print("画像生成完了\n=== 完了 ===")

except Exception as e:
    print("=== 重大エラー発生 ===")
    print(type(e), e)
    traceback.print_exc()
    make_nodata_weather_panel(get_nodata_times(), save_path=OUTFILE)
    sys.exit(1)
