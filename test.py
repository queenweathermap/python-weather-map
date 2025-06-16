import os
import requests


FILENAME = "test.png"
print("=== 現在のディレクトリ ===", os.getcwd())
print("=== ファイル一覧 ===", os.listdir())
print("=== ファイル存在確認 ===", os.path.exists(FILENAME))
if not os.path.exists(FILENAME):
    raise FileNotFoundError(f"{FILENAME}が見つかりません！")
print("=== ファイルサイズ ===", os.path.getsize(FILENAME))


FILENAME = "test.png"
assert os.path.exists(FILENAME), "test.pngが存在しません"
FILESIZE = os.path.getsize(FILENAME)
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]

headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json; charset=utf-8"
}
json_data = {
    "filename": FILENAME,
    "length": FILESIZE
}
print("送信データ:", json_data)
res = requests.post(
    "https://slack.com/api/files.getUploadURLExternal",
    headers=headers,
    json=json_data
)
print("APIレスポンス:", res.text)
