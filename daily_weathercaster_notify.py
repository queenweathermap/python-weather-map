# daily_weathercaster_notify.py
# ===============================================================
# Weathercaster 天気図PDFをDL → JPG変換 → ZIPにまとめ
# Google Driveにアップロード + SlackにURL通知 + 30日前以前を自動削除
# ---------------------------------------------------------------
# - PDFは全種類DL (COMP12など)
# - PDF → JPG(元ファイル名を保持)
# - JPGをZIPにまとめ
# - Google Driveに日付ZIPで保存
# - SlackにURLを通知
# - Driveの古いファイルを30日前以前で自動削除
# ===============================================================

import os
import zipfile
from datetime import datetime
from dotenv import load_dotenv
from pdf2image import convert_from_path

from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import notify_slack

# --- .env 読込 ---
load_dotenv()

# --- 固定設定 ---
SAVE_DIR = "./data"
CHANNEL = os.getenv("SLACK_CHANNEL_ID")
FOLDER_ID = os.getenv("WEATHERCASTER_DRIVE_FOLDER_ID")

# --- 保存ディレクトリ作成 ---
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 1. PDFダウンロード ---
USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
pdf_files = download_weathercaster_pdfs(save_dir=SAVE_DIR, username=USER, password=PASS)

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
        else:
            print(f"[SKIP] PDFが空: {pdf_path}")
    except Exception as e:
        print(f"[ERROR] JPG変換失敗: {pdf_path} - {e}")

# --- 3. ZIPにまとめ ---
if jpg_paths:
    date_str = datetime.now().strftime("%Y%m%d")
    zip_filename = f"weathercharts_{date_str}.zip"
    zip_path = os.path.join(SAVE_DIR, zip_filename)

    with zipfile.ZipFile(zip_path, "w") as zipf:
        for img_path in jpg_paths:
            zipf.write(img_path, arcname=os.path.basename(img_path))
    print(f"[OK] ZIP作成: {zip_path}")

    # --- 4. Google Driveにアップロード ---
    url = upload_to_drive(zip_path, folder_id=FOLDER_ID)
    print(f"[OK] Drive URL: {url}")

    # --- 5. SlackにURL通知 ---
    notify_slack(
        message=f"\u2614 Weathercaster天気図 ({date_str})\n{url}",
        channel=CHANNEL
    )

    # --- 6. Google Driveの古いファイルを削除 ---
    delete_old_files_from_drive(folder_id=FOLDER_ID, older_than_days=30)
else:
    print("[INFO] JPG変換エラー、ZIP作成スキップ")
