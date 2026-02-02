# module/utils/slack_utils.py
# ===============================================================
# Slack通知＆ファイルアップロードユーティリティ（API v2対応）
# ---------------------------------------------------------------
# できること：
#  - テキスト通知（chat.postMessage）
#  - ファイルアップロード（外部アップロード3ステップ方式）
#
# 重要：
#  - files.getUploadURLExternal は「form送信」が最も安定（JSONだと missing 扱いになる事がある）
#  - completeUploadExternal も form送信に寄せて事故を減らす
#
# 必要な環境変数：
#  - SLACK_BOT_TOKEN
#  - SLACK_CHANNEL_ID（例: C0123...）
# ===============================================================

import os
import re
import json
import tempfile
from typing import Sequence, Optional

import requests


# ---------------------------------------------------------------
# Utils
# ---------------------------------------------------------------
def sanitize_filename(filename: str) -> str:
    """
    Slackファイルアップロード用にファイル名をサニタイズ
    （半角英数字・アンダースコア・ピリオド・ハイフン以外は "_" に置換）
    """
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    # 念のため空文字回避
    return safe if safe else "file.bin"


def get_slack_token() -> Optional[str]:
    return os.environ.get("SLACK_BOT_TOKEN")


def _auth_headers(token: str) -> dict:
    # Slack Web API は charset 付きが無難
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
    }


def _print_slack_error(prefix: str, resp_json: dict) -> None:
    """
    Slackのエラーを見やすく出す（ログで原因特定しやすくする）
    """
    err = resp_json.get("error")
    warn = resp_json.get("warning")
    meta = resp_json.get("response_metadata") or {}
    msgs = meta.get("messages")
    print(f"[ERROR] {prefix}: error={err} warning={warn} messages={msgs}")


# ---------------------------------------------------------------
# Text message
# ---------------------------------------------------------------
def send_slack_text(channel: str, message: str) -> None:
    """
    指定チャンネルにテキストメッセージを送信（chat.postMessage）
    """
    token = get_slack_token()
    if not token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel, "text": message}

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    j = r.json()

    if not j.get("ok"):
        _print_slack_error("chat.postMessage failed", j)
    else:
        print(f"[Slack] message sent: {message[:40]}...")


# ---------------------------------------------------------------
# File upload (External upload 3-step)
# ---------------------------------------------------------------
def upload_files_slack(
    channel: str,
    filepaths: list[str],
    *,
    titles: list[str] | None = None,
    initial_comment: str = "",
) -> None:
    """
    複数ファイルをアップロードして、1投稿に束ねる（外部アップロード3-step）
    - channel: "Cxxxx"（チャンネルID）
    - filepaths: 送るローカルファイルパスの配列
    - titles: Slack上での表示タイトル（省略可）
    - initial_comment: 投稿本文（省略可）
    """
    token = get_slack_token()
    if not token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です")
        return

    headers = _auth_headers(token)
    files_meta: list[dict] = []  # [{"id": file_id, "title": "..."}]

    # ---------------------------
    # Step1: getUploadURLExternal
    # ---------------------------
    for idx, p in enumerate(filepaths):
        if not os.path.exists(p):
            print(f"[WARN] file not found: {p}")
            continue

        filename = sanitize_filename(os.path.basename(p))
        length = os.path.getsize(p)

        if length <= 0:
            print(f"[WARN] skip zero size: {p}")
            continue

        # ★最重要：ここは form 送信が安定
        r1 = requests.post(
            "https://slack.com/api/files.getUploadURLExternal",
            headers=headers,
            data={
                "filename": filename,
                "length": str(length),
            },
            timeout=60,
        )
        j1 = r1.json()
        if not j1.get("ok"):
            _print_slack_error("files.getUploadURLExternal failed", j1)
            continue

        upload_url = j1["upload_url"]
        file_id = j1["file_id"]

        # ---------------------------
        # Step2: PUT file body
        # ---------------------------
        with open(p, "rb") as f:
            r2 = requests.put(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )

        if r2.status_code != 200:
            print(f"[ERROR] PUT failed: status={r2.status_code} file={filename} body={(r2.text or '')[:200]}")
            continue

        # 表示タイトル（省略なら filename）
        title = titles[idx] if titles and idx < len(titles) else filename
        files_meta.append({"id": file_id, "title": title})

    if not files_meta:
        print("[WARN] no files to complete")
        return

    # ---------------------------
    # Step3: completeUploadExternal
    # ---------------------------
    # ここも form に寄せる（files は JSON文字列として渡す）
    r3 = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers=headers,
        data={
            "channel_id": channel,
            "initial_comment": initial_comment,
            "files": json.dumps(files_meta, ensure_ascii=False),
        },
        timeout=60,
    )
    j3 = r3.json()
    if not j3.get("ok"):
        _print_slack_error("files.completeUploadExternal failed", j3)
    else:
        print(f"[Slack] uploaded {len(files_meta)} file(s) to channel={channel[:6]}...")


def upload_bytes_slack(
    channel: str,
    files: Sequence[tuple[str, bytes]],
    *,
    initial_comment: str = "",
    titles: Sequence[str] | None = None,
) -> None:
    """
    (filename, bytes) を受け取り、一時ファイルに書いて upload_files_slack() で送る。
    scripts/jma_adv.py の「生成したJPG」を直接Slackへ投げるための橋渡し。
    """
    tmp_paths: list[str] = []
    try:
        for i, (name, blob) in enumerate(files):
            safe = sanitize_filename(name)
            suffix = os.path.splitext(safe)[1] or ".bin"

            # suffix だけだと区別がつかないので prefix も少し入れる
            with tempfile.NamedTemporaryFile(delete=False, prefix="slk_", suffix=suffix) as tf:
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
