import os
import requests

def upload_file_external_slack(channel, filepath, title="天気図", initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    url = "https://slack.com/api/files.upload"
    headers = {
        "Authorization": f"Bearer {bot_token}"
    }
    data = {
        "channels": channel,
        "title": title,
        "initial_comment": initial_comment,
    }
    files = {
        "file": (os.path.basename(filepath), open(filepath, "rb"))
    }
    print("[INFO] files.upload 送信準備OK:", filepath)
    response = requests.post(url, headers=headers, data=data, files=files)
    print("[DEBUG] response.text:", response.text)
    res_json = response.json()
    if not res_json.get("ok"):
        print("Error: files.upload:", res_json)
    else:
        print("[Slack送信] 完了:", res_json)
