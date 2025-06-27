# scripts/main_weather_akita.py
# ========================================================
# 秋田局地 MSMパネル（7段×4列×複数ページ）自動生成＋Zip＋Drive＋Slack通知テンプレ
# 全国版と完全揃え（2025-06-27）
# ========================================================

import os
import sys
from io import StringIO
import traceback
import glob
import xarray as xr
import pandas as pd

from module.utils.gpv_html_parser import find_existing_msm_files
from module.core.gpv_converter import grib2_to_netcdf
from module.core.gpv_data_loader import load_dataset
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import send_slack_message
from module.panel_utils import (
    make_nodata_weather_panel,
    make_local_weather_panel,
    align_datasets_common,
)

# --- パラメータ（全国と揃える） ---
BASE_DIR = "./data"
OUT_PREFIX = "akita_local_msm_map"
NCOLS = 4
NROWS = 7     # 全国と揃える（例：7段）
NPAGES = 4    # 必要に応じて増やせます（4ページに統一）

PIN_LAT = 39.7186
PIN_LON = 140.1024
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=4):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in range(0, 24, 3) if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

def main():
    # --- LOGバッファ ---
    log_buffer = StringIO()
    sys.stdout = sys.stderr = log_buffer

    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        panel_imgs = []

        # --- データ取得（全国版のdownload_gpv_panelに近い実装でもOK） ---
        # ...（従来通り: MSMバイナリ検索→NetCDF変換→open_dataset→align_datasets_common）...
        # ここは全国版の `download_gpv_panel()` 互換を使っても良いです

        # --- パネル生成 ---
        for page in range(NPAGES):
            out_img = f"{OUT_PREFIX}_p{page+1}.jpg"
            # plot_func_list：必要な関数を7つ指定（全国版同様）
            plot_func_list = [
                # 例: plot_emagram_msm_panel, plot_850hpa_temp_wind_700hpa_w_msm, ...
            ]
            # ds, times は各自取得
            make_local_weather_panel(
                ds, times, out_img,
                pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
                lat_range=(38, 41), lon_range=(139, 142),
                plot_func_list=plot_func_list,
                nrows=NROWS, ncols=NCOLS,
            )
            panel_imgs.append(os.path.join(BASE_DIR, out_img))
            print(f"[OK] 保存: {os.path.join(BASE_DIR, out_img)}")

        # --- ZIP作成 ---
        zip_name = f"{OUT_PREFIX}.zip"
        zip_path = os.path.join(BASE_DIR, zip_name)
        print("[STEP3] JPGをZIP圧縮")
        zip_files(panel_imgs, zip_path)
        print(f"[OK] ZIP作成: {zip_path}")

        # --- Drive & Slack通知 ---
        print("[STEP4] Google Driveへアップロード")
        drive_url = upload_to_drive(zip_path)
        print(f"[OK] Drive URL: {drive_url}")

        # --- ファイルリスト＆Slack通知 ---
        file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [zip_name])
        detail_log = log_buffer.getvalue()
        msg = (
            f":earth_asia: 秋田局地MSM天気図パネル {pd.Timestamp.now():%Y%m%d %H:%M}\n"
            "--- LOG ---\n"
            f"{file_log}\n"
            "--- 詳細LOG ---\n"
            f"{detail_log[-1800:]}"
        )
        send_slack_message(msg)

    except Exception as e:
        print("NO DATA: Exception", e)
        traceback.print_exc()
        make_nodata_weather_panel(
            save_path=f"{OUT_PREFIX}_nodata.jpg",
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(1)
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        log_buffer.close()

if __name__ == "__main__":
    main()
