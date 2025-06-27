# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意局地 MSM天気図パネル（7段4列）自動生成・Drive+Slack通知バッチ
# 2025-06-28
# 緯度・経度・都市名・範囲を変えるだけで複数地点運用OK
# ===============================================================

import os
import sys
import traceback
import os
import datetime
import requests
from module.utils.slack_utils import send_slack_text
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify

def main():
    ymd = "20250628"
    hh = "12"
    model = "MSM"
    output_dir = "./output_tokyo"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    city_name = "tokyo"    # ←ここの一行でズーム切替！

    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd, hh=hh, model=model, output_dir=output_dir,
        drive_folder=drive_folder, city_name=city_name
    )
    print("[OK] 任意局地パネル作成 完了")
    print(drive_url)

if __name__ == "__main__":
    main()
