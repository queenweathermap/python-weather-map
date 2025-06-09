# module/slack_utils.py

import requests
import os

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    # 1. アップロードURL取得
    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}"
    }
    data = {
        "filename": os.path.basename(filepath),
        "length": os.path.getsize(filepath),
    }
    res = requests.post(url, headers=headers, json=data).json()
    if not res.get("ok"):
        print("Failed to get upload URL:", res)
        return

    upload_url = res["upload_url"]
    file_id = res["file_id"]

    # 2. ファイルをPUTでアップロード
    with open(filepath, "rb") as f:
        upload_res = requests.put(upload_url, data=f)
    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.status_code)
        return

    # 3. completeUploadExternal でSlackに公開
    complete_url = "https://slack.com/api/files.completeUploadExternal"
    data = {
        "files": [
            {
                "id": file_id,
                "title": title
            }
        ],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    complete_res = requests.post(complete_url, headers=headers, json=data).json()
    if not complete_res.get("ok"):
        print("Failed to complete upload:", complete_res)
        return

    print("[Slack送信] 完了:", complete_res)

# ←ここで何も呼び出さない！
