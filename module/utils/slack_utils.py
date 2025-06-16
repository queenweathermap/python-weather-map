# module/utils/slack_utils.py
# ===============================================
# Slackファイルアップロードユーティリティ（新API v2完全対応・英語実装）
# -----------------------------------------------
# ・ファイル（画像など）をSlackに外部アップロード方式（API v2）で送信
# ・Slack推奨の3ステップ方式で method_deprecated を完全回避
# ・ファイルアップロード時は公開URLの取得やコメント追加も可能
# ・テキストだけの通知（chat.postMessage）も対応
# -----------------------------------------------
# 利用例:
#   from module.utils.slack_utils import upload_file_slack
#   upload_file_slack("C12345678", "weather_map.jpg")
#   from module.utils.slack_utils import send_slack_text
#   send_slack_text("Hello! Weather map updated.")
# 必須パッケージ:
#   pip install requests python-dotenv
# ===============================================

import requests
import os

def upload_file_slack(
    channel,
    filepath,
    title="Weather Map",
    initial_comment="Here is the latest weather map!"
):
    """
    Upload a file to a Slack channel via External Upload (API v2 recommended method).
    channel: Channel ID (e.g., "C12345678")
    filepath: Local file path (e.g., "weather_map.jpg")
    title: Displayed file name in Slack
    initial_comment: First comment text with file
    """
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    if not os.path.exists(filepath):
        print(f"[ERROR] File does not exist: {filepath}")
        return

    filename = os.path.basename(filepath)
    length = int(os.path.getsize(filepath))

    # === Step 1: Get Upload URL (files.getUploadURLExternal) ===
    url_get = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {"filename": filename, "length": length}
    print(f"[INFO] getUploadURLExternal: {data}")
    res1 = requests.post(url_get, headers=headers, json=data)
    res1_json = res1.json()
    print(f"[DEBUG] getUploadURLExternal response: {res1_json}")
    if not res1_json.get("ok"):
        print("[ERROR] Slack: Failed to get upload URL:", res1_json)
        return
    upload_url = res1_json["upload_url"]
    file_id = res1_json["file_id"]

    # === Step 2: PUT file body ===
    print(f"[INFO] Slack PUT upload: {filepath}")
    with open(filepath, "rb") as f:
        put_res = requests.put(upload_url, data=f)
    if put_res.status_code != 200:
        print("[ERROR] Slack: PUT upload failed:", put_res.status_code, put_res.text)
        return

    # === Step 3: Complete upload (files.completeUploadExternal) ===
    url_complete = "https://slack.com/api/files.completeUploadExternal"
    complete_data = {
        "files": [{"id": file_id, "title": title}],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    print(f"[INFO] completeUploadExternal: {complete_data}")
    res3 = requests.post(url_complete, headers=headers, json=complete_data)
    res3_json = res3.json()
    print(f"[DEBUG] completeUploadExternal response: {res3_json}")
    if not res3_json.get("ok"):
        print("[ERROR] Slack file post failed:", res3_json)
    else:
        print("[Slack upload] Done:", res3_json)


def send_slack_text(text):
    """
    Send a simple text message to a Slack channel using chat.postMessage.
    - Useful for notifications, error alerts, etc.
    """
    url = "https://slack.com/api/chat.postMessage"
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    channel = os.environ["SLACK_CHANNEL_ID"]
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "channel": channel,
        "text": text
    }
    res = requests.post(url, headers=headers, json=data)
    if not res.ok or not res.json().get("ok"):
        print("[ERROR] Slack text post failed:", res.text)

# ===============================================
