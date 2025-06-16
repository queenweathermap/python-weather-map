import os
import requests

FILENAME = "test.png"
print("=== カレントディレクトリ ===", os.getcwd())
print("=== ファイル一覧 ===", os.listdir())
print("=== ファイル存在確認 ===", os.path.exists(FILENAME))
if not os.path.exists(FILENAME):
    print("ERROR: ファイルがありません")
    exit(1)


SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
FILENAME = "test.png"
FILESIZE = os.path.getsize(FILENAME)  # int型になる

headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json; charset=utf-8"
}
json_data = {
    "filename": FILENAME,  # 例: "test.png"
    "length": FILESIZE     # 例: 12345  ← 必ずint型!
}

print("送信データ:", json_data)  # デバッグ用
res = requests.post(
    "https://slack.com/api/files.getUploadURLExternal",
    headers=headers,
    json=json_data
)
print("getUploadURLExternal:", res.text)
