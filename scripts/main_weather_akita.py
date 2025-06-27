# scripts/main_weather_akita.py
# ========================================================
# 秋田局地 MSMパネル（6段×12列）自動生成＋ZIP配信テンプレ
# ========================================================

import os
import sys
import traceback
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

BASE_DIR = "./data"
OUT_PREFIX = "akita_local_msm_map"
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
YMD = pd.Timestamp.now().strftime("%Y%m%d")
NCOLS = 12
NPAGES = 1  # 必要に応じて増やせます
CITY_NAME = "Akita City"

def get_gpv_nodata_times(ncols=12):
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in [0, 3, 6, 9, 12, 15, 18, 21] if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    panel_imgs = []

    files = find_existing_msm_files(BASE_URL, YMD)
    # ...データ処理は従来通り...

    # --- ページ分割/画像生成例（1ページのみなら1回ループ） ---
    for page in range(NPAGES):
        out_img = f"{OUT_PREFIX}_p{page+1}.jpg"
        make_local_weather_panel(
            ds, times, out_img,
            pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
            lat_range=(38, 41), lon_range=(139, 142),
            plot_func_list=plot_func_list,
            nrows=6, ncols=NCOLS,
        )
        panel_imgs.append(os.path.join(BASE_DIR, out_img))

    # --- まとめてZIP ---
    zip_path = os.path.join(BASE_DIR, f"{OUT_PREFIX}.zip")
    zip_files(panel_imgs, zip_path)

    # --- Drive & Slack通知 ---
    drive_url = upload_to_drive(zip_path)
    send_slack_message(f"【自動配信】秋田局地MSMパネル（ZIP）\n{drive_url}")

except Exception as e:
    print("NO DATA: Exception", e)
    traceback.print_exc()
    make_nodata_weather_panel(
        save_path=f"{OUT_PREFIX}_nodata.jpg",
        city_name=CITY_NAME,
        times=get_gpv_nodata_times(NCOLS)
    )
    sys.exit(1)
