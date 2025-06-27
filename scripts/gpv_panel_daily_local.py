# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意局地 MSM天気図パネル（7段4列）自動生成・Drive+Slack通知バッチ
# 2025-06-28
# 緯度・経度・都市名・範囲を変えるだけで複数地点運用OK
# ===============================================================

import os
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.slack_utils import send_slack_text

def main():
    # ==== 設定値 ====
    ymd = "20250628"
    hh = "00"
    model = "MSM"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols, npages, nrows = 4, 1, 7

    # --- 任意局地の中心位置・範囲 ---
    city_name = "customlocal"   # 例: yourcity など
    pin_lat, pin_lon = 35.6895, 139.6917     # 例: 東京駅
    lat_range = (34.0, 37.0)
    lon_range = (138.0, 141.0)

    # --- 一括パネル生成＋Drive＋URL取得 ---
    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
    )
        drive_folder=drive_folder,
        ncols=ncols, npages=npages, nrows=nrows,
        city_name=city_name,
        pin_lat=pin_lat, pin_lon=pin_lon, lat_range=lat_range, lon_range=lon_range
    )

    # --- Slack通知 ---
    msg = (
        f":yellow_circle: 任意局地天気図パネル {ymd} UTC{hh}\n"
        f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
        f"{os.path.basename(zip_path)}\n"
        f"{drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
