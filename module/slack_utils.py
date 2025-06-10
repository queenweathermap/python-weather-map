import requests
import os
import json

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが存在しません: {filepath}")
        return

    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    # ← ここで「data」にjson.dumps()で渡すのがポイント
    data = {
        "filename": os.path.basename(filepath),
        "length": int(os.path.getsize(filepath)),
    }
    print(f"headers={headers}")
    print(f"data={data}")
    res = requests.post(url, headers=headers, data=json.dumps(data))
    print(f"res.text={res.text}")
    res_json = res.json()
    print(f"[DEBUG] res_json={res_json}")

    if not res_json.get("ok"):
        print("Error: to get upload URL:", res_json)
        return

    upload_url = res_json["upload_url"]
    file_id = res_json["file_id"]

    with open(filepath, "rb") as f:
        upload_res = requests.put(upload_url, data=f)
    print(f"[DEBUG] upload_res={upload_res.status_code}")

    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.status_code, upload_res.text)
        return

    complete_url = "https://slack.com/api/files.completeUploadExternal"
    complete_headers = headers
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
    print(f"[DEBUG] complete_data={complete_data}")

    complete_res = requests.post(complete_url, headers=complete_headers, json=complete_data)
    complete_json = complete_res.json()
    print(f"[DEBUG] complete_json={complete_json}")

    if not complete_json.get("ok"):
        print("Failed to complete upload:", complete_json)
        return

    print("[Slack送信] 完了:", complete_json)
