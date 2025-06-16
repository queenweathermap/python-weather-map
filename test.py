import os
from module.utils.drive_utils import upload_to_drive
import requests

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
FILENAME = "test.png"

# 1. Google Driveへアップロード＆共有URL取得
drive_url = upload_to_drive(FILENAME)
print("Drive共有URL:", drive_url)

# 2. Slackに共有URLを通知
text = f"ファイルをGoogle Driveにアップロードしました: {drive_url}"
res = requests.post(
    "https://slack.com/api/chat.postMessage",
    headers={
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    },
    json={
        "channel": SLACK_CHANNEL_ID,
        "text": text
    }
)
print("Slack通知:", res.text)
