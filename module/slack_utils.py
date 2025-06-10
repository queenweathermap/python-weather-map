import requests
import os

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが存在しません: {filepath}")
        return

    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}"
    }
    data = {
        "filename": os.path.basename(filepath),
        "length": os.path.getsize(filepath)
    }

    res = requests.post(url, headers=headers, json=data)
    print("res.text:", res.text)
    res_json = res.json()
    if not res_json.get("ok"):
        print("Error: to get upload URL:", res_json)
        return

    upload_url = res_json["upload_url"]
    file_id = res_json["file_id"]

    # ファイルPUTアップロード
    with open(filepath, "rb") as f:
        upload_res = requests.put(upload_url, data=f)
    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.status_code, upload_res.text)
        return

    # completeUploadExternal
    complete_url = "https://slack.com/api/files.completeUploadExternal"
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
    complete_res = requests.post(complete_url, headers=headers, json=complete_data)
    complete_json = complete_res.json()
    print("complete_json:", complete_json)
    if not complete_json.get("ok"):
        print("Failed to complete upload:", complete_json)
        return

    print("[Slack送信] 完了:", complete_json)
