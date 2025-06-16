# module/utils/slack_utils.py
# ===============================================
# Slackファイルアップロード（新API v2推奨方式）
# 2025-06-17 ChatGPT（method_deprecated完全回避・3ステップ）
# -----------------------------------------------
# 利用例:
#   from module.utils.slack_utils import upload_file_slack
#   upload_file_slack("C12345678", "weather_map.jpg")
# ===============================================

import requests
import os

def upload_file_slack(
    channel,
    filepath,
    title="天気図",
    initial_comment="天気図をお届けします！"
):
    """
    Slackチャンネルへファイルを外部アップロード方式（API v2）で送信
    """
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが存在しません: {filepath}")
        return

    filename = os.path.basename(filepath)
    length = int(os.path.getsize(filepath))

    # === 1. アップロードURLを取得 ===
    url_get = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {"filename": filename, "length": length}
    print(f"[INFO] getUploadURLExternal: {data}")
    res1 = requests.post(url_get, headers=headers, json=data)
    res1_json = res1.json()
    print(f"[DEBUG] getUploadURLExternalレスポンス: {res1_json}")
    if not res1_json.get("ok"):
        print("[ERROR] Slack: upload URL取得失敗:", res1_json)
        return
    upload_url = res1_json["upload_url"]
    file_id = res1_json["file_id"]

    # === 2. PUTでファイル本体アップロード ===
    print(f"[INFO] Slack PUTアップロード開始: {filepath}")
    with open(filepath, "rb") as f:
        put_res = requests.put(upload_url, data=f)
    if put_res.status_code != 200:
        print("[ERROR] Slack: PUTアップロード失敗:", put_res.status_code, put_res.text)
        return

    # === 3. 完了通知（completeUploadExternal） ===
    url_complete = "https://slack.com/api/files.completeUploadExternal"
    complete_data = {
        "files": [{"id": file_id, "title": title}],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    print(f"[INFO] completeUploadExternal: {complete_data}")
    res3 = requests.post(url_complete, headers=headers, json=complete_data)
    res3_json = res3.json()
    print(f"[DEBUG] completeUploadExternalレスポンス: {res3_json}")
    if not res3_json.get("ok"):
        print("[ERROR] Slackファイル投稿失敗:", res3_json)
    else:
        print("[Slack送信] 完了:", res3_json)


def send_slack_text(text):
    url = "https://slack.com/api/chat.postMessage"
    bot_token = os.environ["SLACK_BOT_TOKEN"]   # 修正済
    channel = os.environ["SLACK_CHANNEL_ID"]
    headers = {
        "Authorization": f"Bearer {bot_token}",  # 修正済
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "channel": channel,
        "text": text
    }
    res = requests.post(url, headers=headers, json=data)
    if not res.ok or not res.json().get("ok"):
        print("[ERROR] Slack text送信失敗:", res.text)

# ===============================================
