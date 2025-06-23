# daily_weathercaster_notify.py
# ===============================================================
# 気象庁PDF → JPG(300dpi)変換 → ZIP化 → Driveアップロード
# Slackには「実行ログ＋Driveリンク」のみ通知
# ===============================================================

import os
import datetime
import subprocess
import zipfile
from io import StringIO
import sys

from module.utils.download_weathercaster_pdf import download_weathercaster_pdf
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

# --- 保存先 ---
SAVE_DIR = "./data"
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 日付 ---
today = datetime.datetime.now().strftime("%Y%m%d")
pdf_filename = f"{today}_COMP12.pdf"
pdf_path = os.path.join(SAVE_DIR, pdf_filename)
jpg_filename = f"{today}_COMP12.jpg"
jpg_path = os.path.join(SAVE_DIR, jpg_filename)
zip_path = os.path.join(SAVE_DIR, f"{today}_weathercharts.zip")

# --- ログ収集のため出力を一時的に捕捉 ---
log_buffer = StringIO()
sys.stdout = sys.stderr = log_buffer

print(f"[START] {today} 気象庁Weathercaster天気図処理")

try:
    # --- STEP 1: PDFダウンロード ---
    print("[STEP1] PDFダウンロード")
    username = os.environ["WEATHERCASTER_USER"]
    password = os.environ["WEATHERCASTER_PASS"]
    success = download_weathercaster_pdf(username, password, pdf_path)
    if not success:
        raise RuntimeError("PDFダウンロードに失敗しました")

    # --- STEP 2: JPG変換（300dpi） ---
    print("[STEP2] PDFをJPGに変換（300dpi）")
    cmd = f"pdftoppm -jpeg -singlefile -r 300 {pdf_path} {jpg_path[:-4]}"
    subprocess.run(cmd, shell=True, check=True)
    if not os.path.exists(jpg_path):
        raise FileNotFoundError("JPG変換に失敗しました")
    print(f"[OK] JPG出力: {jpg_path}")

    # --- STEP 3: ZIP作成 ---
    print("[STEP3] ZIP圧縮")
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.write(jpg_path, arcname=os.path.basename(jpg_path))
    print(f"[OK] ZIP作成: {zip_path}")

    # --- STEP 4: Google Driveにアップ ---
    print("[STEP4] Google Driveにアップロード")
    drive_url = upload_to_drive(zip_path, folder_id=os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"])
    print(f"[OK] アップロード完了: {drive_url}")

    # --- STEP 5: Slack通知（ログ＋URLのみ） ---
    print("[STEP5] Slack通知（URLのみ）")
    channel_id = os.environ["SLACK_CHANNEL_ID"]
    full_log = log_buffer.getvalue()
    slack_message = (
        f":white_check_mark: {today} 天気図処理が完了しました。\n"
        f"ZIPファイル（JPG 300dpi）はこちら:\n{drive_url}\n\n"
        f"--- 実行ログ ---\n```{full_log[-1800:]}```"
    )
    send_slack_text(channel=channel_id, message=slack_message)

    # --- STEP 6: Drive古いファイル削除 ---
    print("[STEP6] 古いファイル削除（30日以上）")
    delete_old_files_from_drive(
        folder_id=os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"],
        older_than_days=30
    )

except Exception as e:
    error_log = log_buffer.getvalue()
    send_slack_text(
        channel=os.environ["SLACK_CHANNEL_ID"],
        message=f":x: {today} 実行エラーが発生しました\n```{str(e)}\n{error_log[-1500:]}```"
    )
    raise

finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_buffer.close()
