# gpv_panel_daily_msm_akita.py
# ========================================================
# 秋田局地パネル（6段×12列）自動生成スクリプト
# ※現在はGSMデータで運用、NO DATA時も画像出力
# ========================================================


import sys
import traceback
import os
import xarray as xr

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
OUTFILE = "akita_local_msm_map.jpg"

# 秋田市の例
PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "秋田市"

if __name__ == "__main__":
    try:
        print("=== 秋田局地パネル処理開始 ===")
        init_dt = find_existing_init_dt(GSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 12])
        print("GSM最新イニシャル時刻:", init_dt)
        if init_dt is None:
            print("NO DATA: GSMファイルがサーバに見つかりません")
            # 仮の時刻リスト
            import pandas as pd
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        panel_files = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS)
        print("panel_files:", panel_files)

        pattern_files = [f for f in panel_files if f and len(f) == len(GSM_PATTERNS)]
        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            import pandas as pd
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

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
            import pandas as pd
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
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
            import pandas as pd
            now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
            make_nodata_weather_panel(times, save_path=OUTFILE)
            sys.exit(0)

        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        # xarrayのtime値（np.datetime64型）をlistに変換
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        # ==== 【修正】全引数渡し ====
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
        # 例外時もNO DATA画像を出す
        import pandas as pd
        now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [now + pd.Timedelta(hours=3*i) for i in range(NCOLS)]
        make_nodata_weather_panel(times, save_path=OUTFILE)
        sys.exit(1)
