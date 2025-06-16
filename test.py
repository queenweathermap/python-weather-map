import requests
import os

SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']
FILENAME = "test.png"
FILESIZE = os.path.getsize(FILENAME)

print("ファイル名:", FILENAME)
print("ファイルサイズ:", FILESIZE, type(FILESIZE))
print("ファイル存在確認:", os.path.exists(FILENAME))

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
print("APIレスポンス:", res.text)
