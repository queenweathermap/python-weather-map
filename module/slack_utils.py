# module/slack_utils.py

import requests
import os
import json

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    # --- 1. getUploadURLExternal ---
    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "filename": str(os.path.basename(filepath)),   # 念のためstr変換
        "length": int(os.path.getsize(filepath)),      # 念のためint変換
    }
    # 必ずjson.dumpsで送ること！（Slackの外部アップロードはこれでしか通らない場合あり）
    res = requests.post(url, headers=headers, data=json.dumps(data))
    try:
        res_json = res.json()
    except Exception as e:
        print("Failed to decode Slack response:", e, res.text)
        return

    if not res_json.get("ok"):
        print("Error: to get upload URL:", res_json)
        return

    upload_url = res_json["upload_url"]
    file_id = res_json["file_id"]

    print(f"[INFO] アップロードURL取得OK: {upload_url} (file_id: {file_id})")

    # --- 2. PUTでファイル送信 ---
    with open(filepath, "rb") as f:
        upload_res = requests.put(upload_url, data=f)
    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.status_code, upload_res.text)
        return

    # --- 3. completeUploadExternalでSlackに公開 ---
    complete_url = "https://slack.com/api/files.completeUploadExternal"
    complete_headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    complete_data = {
        "files": [
            {
                "id": file_id,
                "title": title
            }
        ],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    complete_res = requests.post(complete_url, headers=complete_headers, data=json.dumps(complete_data))
    try:
        complete_json = complete_res.json()
    except Exception as e:
        print("Failed to decode completeUpload response:", e, complete_res.text)
        return
    if not complete_json.get("ok"):
        print("Failed to complete upload:", complete_json)
        return

    print("[Slack送信] 完了:", complete_json)
