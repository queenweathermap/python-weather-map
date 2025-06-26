# module/utils/slack_utils.py
# ===============================================================
# Slack通知＆ファイルアップロードユーティリティ（API v2完全対応）
# ---------------------------------------------------------------
# ・テキスト通知（chat.postMessage）
# ・ファイルアップロード（推奨の外部アップロード3ステップ方式）
# ・SlackのBotトークンを環境変数で指定：SLACK_BOT_TOKEN
# ・画像／PDFなど各種ファイルをチャンネルに送信可能
# ・チャンネルIDは明示的に指定（例: C12345678）
# ===============================================================

import os
import requests

# --- 共通トークン取得 ---
def get_slack_token():
    return os.environ.get("SLACK_BOT_TOKEN")

# --- ファイルアップロード処理 ---
def upload_file_slack(
    channel,
    filepath,
    title="Weather Map",
    initial_comment="Here is the latest weather map!"
):
    """
    Slackにファイル（画像やPDF）をアップロードする（推奨の外部アップロード方式）
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが見つかりません: {filepath}")
        return

    filename = os.path.basename(filepath)
    length = int(os.path.getsize(filepath))

    # === Step 1: アップロードURL取得 ===
    url_get = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    res1 = requests.post(url_get, headers=headers, json={"filename": filename, "length": length})
    res1_json = res1.json()
    if not res1_json.get("ok"):
        print("[ERROR] Slack: アップロードURL取得失敗:", res1_json)
        return

    upload_url = res1_json["upload_url"]
    file_id = res1_json["file_id"]

    # === Step 2: PUTファイル本体 ===
    with open(filepath, "rb") as f:
        put_res = requests.put(upload_url, data=f)
    if put_res.status_code != 200:
        print("[ERROR] Slack: PUT失敗:", put_res.status_code, put_res.text)
        return

    # === Step 3: アップロード完了通知 ===
    url_complete = "https://slack.com/api/files.completeUploadExternal"
    complete_data = {
        "files": [{"id": file_id, "title": title}],
        "channel_id": channel,
        "initial_comment": initial_comment
    }
    res3 = requests.post(url_complete, headers=headers, json=complete_data)
    res3_json = res3.json()
    if not res3_json.get("ok"):
        print("[ERROR] Slackアップロード完了処理失敗:", res3_json)
    else:
        print(f"[Slack] ファイル送信完了: {title}")

# --- テキストメッセージ送信 ---
def send_slack_text(channel, message):
    """
    指定チャンネルにテキストメッセージを送信（chat.postMessage API）
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "channel": channel,
        "text": message
    }
    res = requests.post(url, headers=headers, json=data)
    res_json = res.json()
    if not res_json.get("ok"):
        print("[ERROR] Slackテキスト送信失敗:", res_json)
    else:
        print(f"[Slack] メッセージ送信完了: {message[:30]}...")

# --- 汎用関数名（他モジュールと統一） ---
def send_slack_message(message, channel=None):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL_ID")
    if not (token and channel):
        print("[ERROR] SLACK_BOT_TOKEN / SLACK_CHANNEL_ID 未設定")
        return
    res = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": message}
    )
    print("[Slack]", res.text)
