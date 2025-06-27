# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知サンプル
# 2025-06-27 ChatGPT 新core設計準拠・テンプレ化
# ===============================================================

import os
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_images
from module.utils.zip_utils import zip_files         # ←★ここを追加！
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

    # --- ② ZIPにまとめる ---
    print("[STEP2] ZIP圧縮")
    zip_path = os.path.join(output_dir, f"panel_japan_{ymd}_{hh}.zip")
    zip_files(panel_imgs, zip_path)

    # --- ③ Google Driveにアップロード ---
    print("[STEP3] Google Driveへアップロード")
    drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
    print(f"[OK] Drive URL: {drive_url}")

    # --- ④ Slackに通知（Drive URLのみ or 添付も可） ---
    print("[STEP4] Slack通知")
    msg = (
        f":white_check_mark: 全国天気図パネル {ymd} UTC{hh}\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url}\n"
        f"--- LOG ---\n"
        # 実行ログや抜粋をここに
    )
    send_slack_text(channel=slack_channel, message=msg)

    # --- ⑤ Google Drive内の古いファイル自動削除 ---
    print("[STEP5] Google Driveの古いファイル自動削除")
    delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)

if __name__ == "__main__":
    main()
