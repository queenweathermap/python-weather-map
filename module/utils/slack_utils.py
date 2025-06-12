# module/slack_utils.py
# ===============================================
# Slack外部ファイルアップロードユーティリティ（Botトークン利用・API 2段階）
# -----------------------------------------------
# ・チャンネルへ画像やファイルを直接アップロード（API v2方式）
# ・Slack Bot Tokenは環境変数 SLACK_BOT_TOKEN で管理
# ・APIエラーやレスポンスも詳細に出力・デバッグしやすい設計
# -----------------------------------------------
# 必要パッケージ: requests
#   pip install requests
# -----------------------------------------------
# 利用例:
#   from module.slack_utils import upload_file_external_slack
#   upload_file_external_slack("C12345678", "weather_map.jpg")
# ===============================================

import requests
import os

def upload_file_external_slack(
    channel,
    filepath,
    title="天気図",
    initial_comment="天気図をお届けします！"
):
    """
    SlackチャンネルへファイルをAPI経由でアップロードし、メッセージ付きで送信
    - channel: チャンネルID（例: "C12345678"）
    - filepath: 送信したいファイルのパス
    - title: Slack上でのファイルタイトル
    - initial_comment: 画像横に表示するメッセージ
    """
    bot_token = os.environ["SLACK_BOT_TOKEN"]

    # --- ファイル存在チェック ---
    if not os.path.exists(filepath):
        print(f"[ERROR] ファイルが存在しません: {filepath}")
        return

    # --- 1. アップロードURL取得（files.getUploadURLExternal）---
    url = "https://slack.com/api/files.getUploadURLExternal"
    headers = {
        "Authorization": f"Bearer {bot_token}"
        # Content-Type不要（API仕様通り）
    }
    data = {
        "filename": os.path.basename(filepath),
        "length": int(os.path.getsize(filepath))
    }
    print(f"[INFO] POST to {url} with {data}")
    res = requests.post(url, headers=headers, json=data)
    print(f"[DEBUG] res.text={res.text}")
    res_json = res.json()
    if not res_json.get("ok"):
        print("Error: to get upload URL:", res_json)
        return

    upload_url = res_json["upload_url"]
    file_id = res_json["file_id"]

    # --- 2. ファイル本体をアップロード（PUT）---
    with open(filepath, "rb") as f:
        upload_res = requests.put(upload_url, data=f)
    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.status_code, upload_res.text)
        return

    # --- 3. アップロード完了をSlackに伝える（files.completeUploadExternal）---
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
    print(f"[DEBUG] complete_json={complete_json}")
    if not complete_json.get("ok"):
        print("Failed to complete upload:", complete_json)
        return

    print("[Slack送信] 完了:", complete_json)

# --- 使い方例（テスト用）---
# upload_file_external_slack("C12345678", "weather_map.jpg")
# 「メッセージだけ送りたい」「複数ファイル同時送信」など拡張があれば追加できる
