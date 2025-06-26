# daily_weathercaster_pdf.py
# ===============================================================
# Weathercaster 天気図PDFを1日1回DL→Driveアップ→Slack通知→1ヶ月前削除
# 実行時間: 日本時間13時（UTC+9 → cron 4時）
# ---------------------------------------------------------------
# ・会員制サイトからBasic認証でPDFを取得（URL固定）
# ・ファイル名は日付付き（例: 20250621_COMP12.pdf）
# ・Google Driveにアップロードして共有リンクを取得
# ・Slackに各URLを投稿通知
# ・Google Drive上のPDFは1ヶ月後に自動削除
# ---------------------------------------------------------------
# 必要: .env または GitHub Secrets に以下を定義
#   - WEATHERCASTER_USER
#   - WEATHERCASTER_PASS
#   - WEATHERCASTER_DRIVE_FOLDER_ID
#   - GOOGLE_SERVICE_ACCOUNT_JSON
#   - SLACK_BOT_TOKEN
#   - SLACK_CHANNEL_ID
# ===============================================================

import os
from dotenv import load_dotenv
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_text

# --- 環境変数の読み込み ---
load_dotenv()

USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
FOLDER_ID = os.getenv("WEATHERCASTER_DRIVE_FOLDER_ID")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")

# --- 1. Weathercasterの天気図PDFを日付付きで一括ダウンロード ---
downloaded = download_weathercaster_pdfs(save_dir="./data", username=USER, password=PASS)

# --- 2. 各PDFをGoogle Driveへアップロードし、Slack通知 ---
for label, path in downloaded:
    try:
        url = upload_to_drive(path, folder_id=FOLDER_ID)
        if url:
            send_slack_text(SLACK_CHANNEL_ID, f"【Weathercaster天気図】{label}\n{url}")
    except Exception as e:
        print(f"[ERROR] アップロードまたは通知失敗: {label} - {e}")

# --- 3. Google Drive内の古いPDF（1ヶ月以上前）を自動削除 ---
try:
    delete_old_files_from_drive(folder_id=FOLDER_ID, older_than_days=30)
except Exception as e:
    print(f"[ERROR] 古いファイル削除中にエラー: {e}")
