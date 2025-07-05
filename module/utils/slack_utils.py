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
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが見つかりません: {filepath}")
        return

    filename = os.path.basename(filepath)
    length = os.path.getsize(filepath)
    if not filename or length == 0:
        print(f"[ERROR] ファイル名またはサイズ不正: {filename}, {length}")
        return

    print(f"[DEBUG] Slack upload: {filename} ({length} bytes)")

    # === Step 1: アップロードURL取得 ===
    url_get = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "filename": str(filename),
        "length": int(length)
    }
    res1 = requests.post(url_get, headers=headers, json=payload)
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

