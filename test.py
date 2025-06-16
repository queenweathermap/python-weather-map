import requests
import os

SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']
FILENAME = "test.png"

with open(FILENAME, "rb") as f:
    response = requests.post(
        "https://slack.com/api/files.upload",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        data={
            "channels": SLACK_CHANNEL_ID,
            "initial_comment": "GitHub Actionsから画像テスト送信",
        },
        files={"file": f}
    )
print(response.text)
