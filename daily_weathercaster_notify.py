# daily_weathercaster_notify.py
# ===============================================================
# 気象庁Weathercaster PDFをJPGに変換し、ZIP化して
# Google Driveへアップ、Slack通知する自動処理スクリプト
# ===============================================================

import os
import glob
import zipfile
import shutil
from datetime import datetime

from module.utils.download_weathercaster_pdf import download_weathercaster_pdf
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message

# --- 出力ディレクトリ ---
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

# --- 日付をファイル名に使用（例: 20250621） ---
today_str = datetime.now().strftime("%Y%m%d")
zip_filename = f"{today_str}_COMP12.zip"
zip_path = os.path.join(output_dir, zip_filename)

# --- ステップ1: PDFダウンロード ---
print("== PDFダウンロード ==")
pdf_paths = download_weathercaster_pdf(output_dir=output_dir)

# --- ステップ2: PDF → JPG変換 ---
print("== JPG変換 ==")
jpg_paths = []
for pdf_path in pdf_paths:
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    output_prefix = os.path.join(output_dir, base)
    cmd = f"pdftoppm -jpeg -singlefile {pdf_path} {output_prefix}"
    print(f"[CMD] {cmd}")
    os.system(cmd)  # jpgファイルが {output_prefix}.jpg として出力される
    jpg_path = f"{output_prefix}.jpg"
    if os.path.exists(jpg_path):
        jpg_paths.append(jpg_path)

# --- ステップ3: ZIP圧縮 ---
print("== ZIP圧縮 ==")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
    for jpg in jpg_paths:
        zipf.write(jpg, arcname=os.path.basename(jpg))
print(f"[OK] ZIPファイル作成: {zip_path}")

# --- ステップ4: Google Driveへアップロード ---
print("== Google Driveアップロード ==")
drive_url = upload_to_drive(file_path=zip_path, folder_id=os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"])
print(f"[OK] Drive URL: {drive_url}")

# --- ステップ5: Slack通知 ---
print("== Slack通知 ==")
send_slack_message(f"📡 本日の気象庁天気図をアップロードしました（JPG ZIP）\n{drive_url}")

# --- ステップ6: 30日より古いファイルをDriveから削除 ---
print("== 古いファイルの削除 ==")
delete_old_files_from_drive(folder_id=os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"], older_than_days=30)

print("== 完了 ==")
