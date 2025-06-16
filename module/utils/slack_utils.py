# module/utils/slack_utils.py
# ===============================================
# Slackファイルアップロード（API v2）ユーティリティ
# 2025-06-17 改訂 by ChatGPT（method_deprecated完全回避＆最新推奨方式）
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
    Slackチャンネルへファイルを直接アップロードし、メッセージ付きで送信（API v2）
    """
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが存在しません: {filepath}")
        return

    url = "https://slack.com/api/files.upload"
    with open(filepath, "rb") as file_content:
        files = {
            "file": (os.path.basename(filepath), file_content)
        }
        data = {
            "channels": channel,
            "title": title,
            "initial_comment": initial_comment,
        }
        headers = {
            "Authorization": f"Bearer {bot_token}"
        }
        print(f"[INFO] Slackにアップロード開始: {filepath}")
        response = requests.post(url, headers=headers, files=files, data=data)
        try:
            res_json = response.json()
        except Exception:
            res_json = {}
        print(f"[DEBUG] Slackファイル投稿APIレスポンス: {response.text}")
        if not res_json.get("ok"):
            print("[ERROR] Slackファイルアップロード失敗:", res_json)
        else:
            print("[Slack送信] 完了:", res_json.get("file", {}).get("permalink", ""))

# ===============================================
