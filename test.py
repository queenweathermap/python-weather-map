import requests
import os

SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']

FILENAME = "test.png"
FILESIZE = os.path.getsize(FILENAME)  # 自動取得

headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json; charset=utf-8"
}
json_data = {
    "filename": FILENAME,
    "length": FILESIZE
}

res = requests.post(
    "https://slack.com/api/files.getUploadURLExternal",
    headers=headers,
    json=json_data
)
print(res.text)  # 結果が{"ok":true, ...}になればOK!
