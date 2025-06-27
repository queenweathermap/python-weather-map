# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知サンプル
# 2025-06-27 ChatGPT 新core設計準拠・テンプレ化
# ===============================================================

import os
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_images
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

def main():
    ymd = "20240622"
    hh = "12"
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    ncols = 4   # 横4列ずつ
    npages = 4  # 4ページ
    slack_channel = os.environ["SLACK_CHANNEL_ID"]

    # --- ① 天気図パネル画像の4ページ生成 ---
    print("[STEP1] 天気図画像（複数ページ）生成")
    # ここでは画像ファイル名リストを返すよう設計
    panel_imgs = generate_japan_panel_images(
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
        ncols=ncols,
        npages=npages
    )
    # 例: ["./data/panel_japan_20240622_p1.jpg", ..., "./data/panel_japan_20240622_p4.jpg"]

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
        f":white_check_mark: {ymd} {hh} 全国天気図パネル（{npages}ページZIP）\n"
        f"Google Driveリンク: {drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

    # --- ⑤ Google Drive内の古いファイル自動削除 ---
    print("[STEP5] Google Driveの古いファイル自動削除")
    delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)

if __name__ == "__main__":
    main()
