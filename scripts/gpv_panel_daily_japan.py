# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知サンプル
# 2025-06-27 ChatGPT 新core設計準拠・テンプレ化
# ===============================================================

import os
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text


def main():
    ymd = "20240622"
    hh = "12"
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    ncols = 4
    npages = 4

    generate_japan_panel_and_notify(
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=ncols,
        npages=npages,
    )

if __name__ == "__main__":
    main()
