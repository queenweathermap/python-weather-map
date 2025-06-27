# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-28
# ===============================================================

import os
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.slack_utils import send_slack_text

def main():
    # ==== 設定値 ====
    ymd = "20250628"              # 例: 実運用時は最新イニシャル自動化OK
    hh = "00"
    model = "HYBRID"              # GSM/MSM/HYBRID
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols, npages, nrows = 4, 4, 7
    city_name = "japan"

    # --- 一括パネル生成＋Drive＋URL取得 ---
    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd, hh=hh, model=model, output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=ncols, npages=npages, nrows=nrows,
        city_name=city_name
    )

    # --- Slack通知 ---
    msg = (
        f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
        f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
        f"{os.path.basename(zip_path)}\n"
        f"{drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
