import os
import requests

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
FILENAME = "test.png"
FILESIZE = os.path.getsize(FILENAME)

# 1. アップロード用URLを取得
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
print("getUploadURLExternal:", res.text)
resp = res.json()
if not resp.get("ok"):
    exit(1)
upload_url = resp["upload_url"]
file_id = resp["file_id"]

# 2. 実ファイルをPUTアップロード
with open(FILENAME, "rb") as f:
    put_res = requests.put(upload_url, data=f)
print("PUT:", put_res.status_code, put_res.text)

# 3. アップロード完了通知
complete_data = {
    "files": [
        {
            "id": file_id,
        }
    ],
    "channel_id": SLACK_CHANNEL_ID,
    "initial_comment": "GitHub Actions経由のアップロードテスト"
}
complete_res = requests.post(
    "https://slack.com/api/files.completeUploadExternal",
    headers=headers,
    json=complete_data
)
print("completeUploadExternal:", complete_res.text)
