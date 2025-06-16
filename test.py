import os
import requests

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
FILENAME = "test.png"

with open(FILENAME, "rb") as f:
    res = requests.post(
        "https://slack.com/api/files.upload",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        data={"channels": SLACK_CHANNEL_ID},
        files={"file": (FILENAME, f, "image/png")}
    )
print(res.text)
