# module/slack_utils.py

import requests
import os
import json

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    # 1. アップロードURL取得
    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "filename": os.path.basename(filepath),
        "length": os.path.getsize(filepath),
    }
    # 必ずContent-Type: application/jsonで送信
    res = requests.post(url, headers=headers, data=json.dumps(data)).json()
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
    headers2 = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data2 = {
        "files": [
            {
                "id": file_id,
                "title": title
            }
        ],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    complete_res = requests.post(complete_url, headers=headers2, data=json.dumps(data2)).json()
    if not complete_res.get("ok"):
        print("Failed to complete upload:", complete_res)
        return

    print("[Slack送信] 完了:", complete_res)
