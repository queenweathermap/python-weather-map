# test.py
# ===============================================
# Google Driveに画像をアップロードし、共有URLをSlackに投稿するテストスクリプト
# -----------------------------------------------
# 必要環境変数:
#   GOOGLE_SERVICE_ACCOUNT_JSON: サービスアカウントJSON文字列
#   DRIVE_FOLDER_ID: アップロード先のGoogle DriveフォルダID
#   SLACK_BOT_TOKEN: Slack Bot User OAuth Token
#   SLACK_CHANNEL_ID: 通知先チャンネルID（例: "C12345678"）
# 必要pipパッケージ:
#   pip install google-api-python-client google-auth-httplib2 google-auth requests python-dotenv
# ===============================================

import os
import json
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==== 環境変数取得 ====
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
FILENAME = "test.png"  # アップロードするファイル名

# ==== Google Driveにファイルをアップロードし共有リンク取得 ====
def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    # サービスアカウント認証
    creds = service_account.Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=creds)
    file_metadata = {
        "name": os.path.basename(file_path),
        "parents": [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    file_id = uploaded["id"]
    # 共有設定
    service.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()
    share_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    print("[INFO] Google Driveアップロード完了:", share_url)
    return share_url

# ==== Slackにメッセージとして通知 ====
def post_to_slack(channel, text):
    url = "https://slack.com/api/chat.postMessage"
    data = {
        "channel": channel,
        "text": text
    }
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    response = requests.post(url, headers=headers, data=data)
    print("[INFO] Slack通知レスポンス:", response.text)
    return response

# ==== メイン処理 ====
if __name__ == "__main__":
    if not os.path.exists(FILENAME):
        print(f"[ERROR] ファイルが存在しません: {FILENAME}")
        exit(1)
    # 1. Driveにアップロード→URL取得
    url = upload_to_drive(FILENAME)
    # 2. SlackへURLを通知
    post_to_slack(
        SLACK_CHANNEL_ID,
        f"Google Driveに画像をアップロードしました！\n{url}"
    )
