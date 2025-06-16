import requests
import os
SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']


# ======= 設定 =======
SLACK_BOT_TOKEN = "xoxb-1240646929364-9017850320086-iwMExKk0giUE43hrG1DA9org"   # ←あなたのBot User OAuth Token
FILENAME = "test.png"       # 実際のファイル名
FILESIZE = 37788           # バイト単位（例：os.path.getsize("test.png")で取得可能）

# ======= リクエスト =======
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
print(res.text)  # ← 結果が {"ok":true, ...} になればOK！
