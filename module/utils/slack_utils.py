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
import re
import requests
import json

# 追加（既存の import 群の下あたりに置いてOK）
def upload_files_slack(
    channel: str,
    filepaths: list[str],
    *,
    titles: list[str] | None = None,
    initial_comment: str = ""
) -> None:
    """
    複数ファイルを1つの投稿でアップロード（外部アップロード 3-step をまとめて実行）
    - channel: "Cxxxx"（チャンネルID）
    - filepaths: 送るローカルファイルパスの配列（2枚想定だが複数OK）
    - titles: Slack上での表示タイトル（省略可）
    - initial_comment: 投稿本文（省略可）
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return

    headers = {"Authorization": f"Bearer {bot_token}"}
    files_meta = []  # [{"id": file_id, "title": "..."}]

    for idx, p in enumerate(filepaths):
        if not os.path.exists(p):
            print(f"[WARN] ファイルが見つかりません: {p}")
            continue

        filename = sanitize_filename(os.path.basename(p))
        length = os.path.getsize(p)
        if length <= 0:
            print(f"[WARN] サイズ0のためスキップ: {p}")
            continue

        # Step1: get upload URL
        r1 = requests.post(
            "https://slack.com/api/files.getUploadURLExternal",
            headers=headers,
            json={"filename": filename, "length": length},
            timeout=60,
        )
        j1 = r1.json()
        if not j1.get("ok"):
            print("[ERROR] getUploadURLExternal 失敗:", j1)
            continue
        upload_url = j1["upload_url"]
        file_id = j1["file_id"]

        # Step2: PUT file body
        with open(p, "rb") as f:
            r2 = requests.put(upload_url, data=f, timeout=300)
        if r2.status_code != 200:
            print("[ERROR] PUT 失敗:", r2.status_code, r2.text[:200])
            continue

        # 投稿時の表示タイトル
        title = titles[idx] if titles and idx < len(titles) else filename
        files_meta.append({"id": file_id, "title": title})

    if not files_meta:
        print("[WARN] アップロード対象がありませんでした")
        return

    # Step3: complete (複数ファイルを1投稿に束ねる)
    r3 = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers=headers,
        json={
            "channel_id": channel,
            "initial_comment": initial_comment,
            "files": files_meta,
        },
        timeout=60,
    )
    j3 = r3.json()
    if not j3.get("ok"):
        print("[ERROR] completeUploadExternal 失敗:", j3)
    else:
        print(f"[Slack] ファイル {len(files_meta)}件を1投稿で送信しました")


def sanitize_filename(filename):
    """
    Slackファイルアップロード用にファイル名をサニタイズ（半角英数字・アンダースコア・ピリオド以外除去）
    """
    return re.sub(r'[^a-zA-Z0-9_.]', '_', filename)



# --- 共通トークン取得 ---
def get_slack_token():
    return os.environ.get("SLACK_BOT_TOKEN")


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
    }
    data = {
        "channel": channel,
        "text": message
    }
    import json
    print("[DEBUG] send_slack_text data:", json.dumps(data, ensure_ascii=False))

    res = requests.post(url, headers=headers, json=data)
    res_json = res.json()
    if not res_json.get("ok"):
        print("[ERROR] Slackテキスト送信失敗:", res_json)
    else:
        print(f"[Slack] メッセージ送信完了: {message[:30]}...")


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

    filename = sanitize_filename(os.path.basename(filepath))
    if not filename:
        print("[ERROR] ファイル名が空です！: ", filepath)
        return
    
    length = os.path.getsize(filepath)
    if not isinstance(length, int) or length <= 0:
        print(f"[ERROR] ファイルサイズ不正: length={length}, path={filepath}")
        return
    
    print(f"[CHECK] filename='{filename}', length={length}")
    print(f"[DEBUG] filename type: {type(filename)}, length type: {type(length)}")
    
    url_get = "https://slack.com/api/files.getUploadURLExternal"
    headers = {"Authorization": f"Bearer {bot_token}"}
    payload = {"filename": filename, "length": length}
    print("[DEBUG] payload-dict:", payload)
    print("[DEBUG] payload-json:", json.dumps(payload))

    res1 = requests.post(url_get, headers=headers, json=payload)
    print("[DEBUG] files.getUploadURLExternal:", res1.text)

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
