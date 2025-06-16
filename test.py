import requests
import os

SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']
FILENAME = "test.png"

# ファイル存在チェック
assert os.path.exists(FILENAME), "ファイルがありません"

print("ファイル名:", FILENAME)
print("ファイルサイズ:", os.path.getsize(FILENAME), type(os.path.getsize(FILENAME)))
print("ファイル存在確認:", os.path.exists(FILENAME))

with open(FILENAME, "rb") as f:
    res = requests.post(
        "https://slack.com/api/files.upload",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        },
        data={
            "channels": SLACK_CHANNEL_ID,
            "initial_comment": "Slack APIテスト送信 by Actions",
            "title": "Slack upload test"
        },
        files={
            "file": (FILENAME, f, "image/png")
        }
    )

print(res.text)
