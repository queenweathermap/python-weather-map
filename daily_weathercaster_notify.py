# daily_weathercaster_notify.py
# ===============================================================
# Weathercaster 天気図PDFを → JPG変換 → ZIP化 → DriveにUP → Slack通知（ログ付き）
# ===============================================================

import os
from dotenv import load_dotenv
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message
from pdf2image import convert_from_path
import zipfile
from datetime import datetime

# --- .env読込 ---
load_dotenv()

# --- 設定 ---
SAVE_DIR = "./data"
USERNAME = os.getenv("WEATHERCASTER_USER")
PASSWORD = os.getenv("WEATHERCASTER_PASS")
DRIVE_FOLDER_ID = os.getenv("WEATHERCASTER_DRIVE_FOLDER_ID")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")

# --- ログ格納 ---
log_lines = []

def log(msg):
    print(msg)
    log_lines.append(msg)

# --- フォルダ作成 ---
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 1. PDFダウンロード ---
pdf_files = download_weathercaster_pdfs(save_dir=SAVE_DIR, username=USERNAME, password=PASSWORD)
log(f"✔ PDF {len(pdf_files)}件ダウンロード成功")

# --- 2. PDF → JPG変換 ---
jpg_paths = []
for label, pdf_path in pdf_files:
    try:
        pages = convert_from_path(pdf_path, dpi=200)
        if pages:
            jpg_path = pdf_path.replace(".pdf", ".jpg")
            pages[0].save(jpg_path, "JPEG")
            jpg_paths.append(jpg_path)
            log(f"✔ JPG変換: {os.path.basename(jpg_path)}")
        else:
            log(f"⚠ 空PDFスキップ: {os.path.basename(pdf_path)}")
    except Exception as e:
        log(f"❌ JPG変換失敗: {os.path.basename(pdf_path)} - {e}")

# --- 3. ZIP化 ---
today = datetime.now().strftime("%Y%m%d")
zip_path = os.path.join(SAVE_DIR, f"weathercharts_{today}.zip")
if jpg_paths:
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for img_path in jpg_paths:
            zipf.write(img_path, arcname=os.path.basename(img_path))
    log(f"✔ ZIP作成: {os.path.basename(zip_path)}")
else:
    log("⚠ JPGなし。ZIPスキップ")

# --- 4. Google Driveアップロード ---
if jpg_paths:
    url = upload_to_drive(zip_path, folder_id=DRIVE_FOLDER_ID)
    log(f"✔ Google Driveアップロード: {url}")
else:
    url = None
    log("⚠ Driveアップロードスキップ")

# --- 5. 古いファイル削除（30日以上） ---
try:
    delete_old_files_from_drive(folder_id=DRIVE_FOLDER_ID, older_than_days=30)
    log("🗑 30日以上前のファイル削除済")
except Exception as e:
    log(f"❌ Drive削除失敗: {e}")

# --- 6. Slack通知（ログ付き） ---
if url:
    message = f"【Weathercaster 実行ログ】\n\n" + "\n".join(log_lines)
    send_slack_message(SLACK_CHANNEL_ID, message)
    log("✔ Slack通知完了")
else:
    log("⚠ Slack通知スキップ（URLなし）")
