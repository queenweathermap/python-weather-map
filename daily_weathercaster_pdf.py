# daily_weathercaster_pdf.py
# ===============================================================
# Weathercaster 天気図PDFを1日1回DL→Driveアップ→Slack通知→1ヶ月前削除
# 実行時間: 日本時間13時（UTC+9 → cron 4時）
# ---------------------------------------------------------------
# 必要: .env または GitHub Secrets に以下を定義
#   - WEATHERCASTER_USER
#   - WEATHERCASTER_PASS
#   - WEATHERCASTER_DRIVE_FOLDER_ID
# ===============================================================

import os
from dotenv import load_dotenv
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import notify_to_slack

load_dotenv()

USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
FOLDER_ID = os.getenv("WEATHERCASTER_DRIVE_FOLDER_ID")

# 1. PDFを日付付きでダウンロード
downloaded = download_weathercaster_pdfs("./data", USER, PASS)

# 2. Driveアップロード & Slack通知
for label, path in downloaded:
    url = upload_to_drive(path, folder_id=FOLDER_ID)
    if url:
        notify_to_slack(f"【Weathercaster天気図】{label}", url)

# 3. 1ヶ月以上前のPDFを削除
delete_old_files_from_drive(FOLDER_ID, older_than_days=30)
