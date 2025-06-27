# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知サンプル
# 2025-06-27 ChatGPT 新core設計準拠・テンプレ化
# ===============================================================

import os
import glob
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

def main():
    # ==== 設定 ====
    ymd = "20250624"           # 出力日付（自動化時は自動取得も可）
    hh = "00"                  # UTC時刻
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols = 4
    npages = 4

    # ==== ① パネル画像生成 ====
    generate_japan_panel_and_notify(
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
        drive_folder=None,  # Drive/Slack通知はここでは行わない
        ncols=ncols,
        npages=npages,
    )

    # ==== ② 画像リスト取得・ZIP化 ====
    pattern = f"panel_japan_{ymd}_UTC{hh}_p*.jpg"
    panel_imgs = sorted(glob.glob(os.path.join(output_dir, pattern)))
    zip_name = f"panel_japan_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)

    # ==== ③ Google Driveにアップロード ====
    drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
    if not drive_url:
        drive_url = "(未アップロード)"

    # ==== ④ Slack通知 ====
    file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [zip_name])
    msg = (
        f":チェックマーク_緑: 全国天気図パネル {ymd} UTC{hh}\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url}\n"
        "--- LOG ---\n"
        f"{file_log}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
