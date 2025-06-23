# daily_weathercaster_notify.py
# ===============================================================
# Weathercaster 天気図PDF → JPG → ZIP → Google Drive & Slack通知
# ---------------------------------------------------------------
# ・Google Drive: ZIPファイルを日付名で保存
# ・Slack: URL通知
# ・30日以上前のファイルをDriveから削除
# ===============================================================

import os
import zipfile
from datetime import datetime
from dotenv import load_dotenv
from pdf2image import convert_from_path
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

# --- .env読み込み ---
load_dotenv()

# --- 固定設定 ---
SAVE_DIR = "./data"
os.makedirs(SAVE_DIR, exist_ok=True)

SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")
DRIVE_FOLDER_ID = os.getenv("WEATHERCASTER_DRIVE_FOLDER_ID")
today_str = datetime.now().strftime("%Y%m%d")
ZIP_FILENAME = f"{today_str}_weathercharts.zip"
ZIP_PATH = os.path.join(SAVE_DIR, ZIP_FILENAME)

# --- 1. PDFダウンロード ---
user = os.getenv("WEATHERCASTER_USER")
password = os.getenv("WEATHERCASTER_PASS")
pdf_files = download_weathercaster_pdfs(SAVE_DIR, user, password)

# --- 2. PDF → JPG変換 ---
jpg_paths = []
for label, pdf_path in pdf_files:
    try:
        pages = convert_from_path(pdf_path, dpi=200)
        if pages:
            jpg_path = pdf_path.replace(".pdf", ".jpg")
            pages[0].save(jpg_path, "JPEG")
            jpg_paths.append(jpg_path)
            print(f"[OK] JPG変換: {jpg_path}")
    except Exception as e:
        print(f"[ERROR] JPG変換失敗: {pdf_path} - {e}")

# --- 3. JPGをZIPにまとめる ---
if jpg_paths:
    with zipfile.ZipFile(ZIP_PATH, "w") as zipf:
        for img in jpg_paths:
            zipf.write(img, arcname=os.path.basename(img))
    print(f"[OK] ZIP作成: {ZIP_PATH}")

    # --- 4. Google Driveにアップロード ---
    drive_url = upload_to_drive(ZIP_PATH, DRIVE_FOLDER_ID)
    if drive_url:
        # --- 5. Slack通知 ---
        send_slack_text(SLACK_CHANNEL, f"📦 {ZIP_FILENAME} をアップロードしました\n{drive_url}")

    # --- 6. 古いファイル削除（30日以上前）---
    delete_old_files_from_drive(DRIVE_FOLDER_ID, days=30)

else:
    print("[INFO] JPGが生成されなかったため処理スキップ")
