# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知バッチ
# 2025-06-27 ChatGPT 新core設計・現行運用推奨版
# ===============================================================

import os
import glob
import sys
from io import StringIO
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_images
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

def main():
    # ==== 設定 ====
    ymd = "20250624"
    hh = "00"
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols = 4
    npages = 4

    # ==== ログバッファ設定 ====
    log_buffer = StringIO()
    orig_stdout = sys.stdout
    sys.stdout = log_buffer
    print(f"[START] {ymd} 全国天気図パネル自動処理")
    try:
        # ① パネル画像生成
        print("[STEP1] パネル画像生成")
        panel_imgs = generate_japan_panel_images(
            ymd=ymd,
            hh=hh,
            model=model,
            output_dir=output_dir,
            ncols=ncols,
            npages=npages,
        )

        # ② ZIP化
        print("[STEP2] ZIP圧縮")
        zip_name = f"panel_japan_{ymd}_UTC{hh}.zip"
        zip_path = os.path.join(output_dir, zip_name)
        zip_files(panel_imgs, zip_path)
        print(f"[OK] ZIP作成: {zip_path}")

        # ③ Google Driveアップロード
        print("[STEP3] Google Driveへアップロード")
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
        print(f"[OK] Drive URL: {drive_url}")

        # ④ Drive古ファイル自動削除
        print("[STEP4] Google Drive古ファイル削除")
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")

    finally:
        sys.stdout = orig_stdout
        log_txt = log_buffer.getvalue()
        log_buffer.close()

    # ==== Slack通知 ====
    msg = (
        f"white_check_mark: 全国天気図パネル {ymd} UTC{hh}\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url if 'drive_url' in locals() else '(未アップロード)'}\n"
        "--- LOG ---\n"
        f"```{log_txt[-1800:]}```"  # Slack投稿は最大2000文字制限
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
