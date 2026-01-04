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
import tempfile
from typing import Sequence, Optional


def sanitize_filename(filename: str) -> str:
    """
    Slackファイルアップロード用にファイル名をサニタイズ
    （半角英数字・アンダースコア・ピリオド・ハイフン以外除去）
    """
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)


# --- 共通トークン取得 ---
def get_slack_token() -> Optional[str]:
    return os.environ.get("SLACK_BOT_TOKEN")


def upload_files_slack(
    channel: str,
    filepaths: list[str],
    *,
    titles: list[str] | None = None,
    initial_comment: str = "",
) -> None:
    """
    複数ファイルを1つの投稿でアップロード（外部アップロード 3-step をまとめて実行）
    - channel: "Cxxxx"（チャンネルID）
    - filepaths: 送るローカルファイルパスの配列
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

        # Step2: PUT file body（Content-Type明示が安定）
        with open(p, "rb") as f:
            r2 = requests.put(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )
        if r2.status_code != 200:
            print("[ERROR] PUT 失敗:", r2.status_code, (r2.text or "")[:200])
            continue

        # 投稿時の表示タイトル
        title = titles[idx] if titles and idx < len(titles) else filename
        files_meta.append({"id": file_id, "title": title})

    if not files_meta:
        print("[WARN] アップロード対象がありませんでした")
        return

    # Step3: complete（複数ファイルを1投稿に束ねる）
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


def upload_bytes_slack(
    channel: str,
    files: Sequence[tuple[str, bytes]],
    *,
    initial_comment: str = "",
    titles: Sequence[str] | None = None,
) -> None:
    """
    (filename, bytes) を受け取り、一時ファイルに書いて upload_files_slack() で送る。
    adv_jma.py の「生成したJPG」を直接Slackへ投げるための橋渡し。
    """
    tmp_paths: list[str] = []
    try:
        for _i, (name, blob) in enumerate(files):
            safe = sanitize_filename(name)
            suffix = os.path.splitext(safe)[1] or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
                tf.write(blob)
                tmp_paths.append(tf.name)

        upload_files_slack(
            channel=channel,
            filepaths=tmp_paths,
            titles=list(titles) if titles else None,
            initial_comment=initial_comment,
        )
    finally:
        for p in tmp_paths:
            try:
                os.remove(p)
            except Exception:
                pass


def send_slack_text(channel: str, message: str) -> None:
    """
    指定チャンネルにテキストメッセージを送信（chat.postMessage API）
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return

    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {bot_token}"}
    data = {"channel": channel, "text": message}

    res = requests.post(url, headers=headers, json=data, timeout=30)
    res_json = res.json()
    if not res_json.get("ok"):
        print("[ERROR] Slackテキスト送信失敗:", res_json)
    else:
        print(f"[Slack] メッセージ送信完了: {message[:30]}...")


def upload_file_slack(
    channel: str,
    filepath: str,
    title: str = "Weather Map",
    initial_comment: str = "Here is the latest weather map!",
) -> None:
    """
    単発アップロードは upload_files_slack() のラッパーに統一
    （二重実装による修正漏れ事故を防ぐ）
    """
    upload_files_slack(channel, [filepath], titles=[title], initial_comment=initial_comment)
