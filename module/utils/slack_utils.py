# module/utils/slack_utils.py
# ===============================================================
# Slack通知＆ファイルアップロードユーティリティ（API v2対応）
# ---------------------------------------------------------------
# できること：
#  - テキスト通知（chat.postMessage）
#  - ファイルアップロード（外部アップロード3ステップ方式）
#  - “天気図配信” の静かな通知（Incoming Webhook 優先 / Bot token フォールバック）
#
# 必要な環境変数（Bot token方式）：
#  - SLACK_BOT_TOKEN
#  - SLACK_CHANNEL_ID（例: C0123...）
#
# 必要な環境変数（Webhook方式）：
#  - SLACK_WEBHOOK_URL（チャンネル #wx-python はWebhook側設定で固定）
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
    return safe if safe else "file.bin"


def get_slack_token() -> Optional[str]:
    return os.environ.get("SLACK_BOT_TOKEN")


def get_default_channel_id() -> Optional[str]:
    return os.environ.get("SLACK_CHANNEL_ID")


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
    }


def _print_slack_error(prefix: str, resp_json: dict) -> None:
    err = resp_json.get("error")
    warn = resp_json.get("warning")
    meta = resp_json.get("response_metadata") or {}
    msgs = meta.get("messages")
    print(f"[ERROR] {prefix}: error={err} warning={warn} messages={msgs}")


# ---------------------------------------------------------------
# Text message (Bot token)
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


def send_slack_text_default(message: str) -> None:
    """
    SLACK_CHANNEL_ID 宛に送る簡易ラッパー（Bot token方式）
    """
    ch = get_default_channel_id()
    if not ch:
        print("[Slack] SLACK_CHANNEL_ID not set -> skip")
        return
    send_slack_text(ch, message)


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

    # Step1: getUploadURLExternal
    for idx, p in enumerate(filepaths):
        if not os.path.exists(p):
            print(f"[WARN] file not found: {p}")
            continue

        filename = sanitize_filename(os.path.basename(p))
        length = os.path.getsize(p)

        if length <= 0:
            print(f"[WARN] skip zero size: {p}")
            continue

        r1 = requests.post(
            "https://slack.com/api/files.getUploadURLExternal",
            headers=headers,
            data={"filename": filename, "length": str(length)},
            timeout=60,
        )
        j1 = r1.json()
        if not j1.get("ok"):
            _print_slack_error("files.getUploadURLExternal failed", j1)
            continue

        upload_url = j1["upload_url"]
        file_id = j1["file_id"]

        # Step2: PUT file body
        with open(p, "rb") as f:
            r2 = requests.put(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )

        if r2.status_code != 200:
            print(
                f"[ERROR] PUT failed: status={r2.status_code} file={filename} body={(r2.text or '')[:200]}"
            )
            continue

        title = titles[idx] if titles and idx < len(titles) else filename
        files_meta.append({"id": file_id, "title": title})

    if not files_meta:
        print("[WARN] no files to complete")
        return

    # Step3: completeUploadExternal
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
    """
    tmp_paths: list[str] = []
    try:
        for i, (name, blob) in enumerate(files):
            safe = sanitize_filename(name)
            suffix = os.path.splitext(safe)[1] or ".bin"
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
    """
    upload_files_slack(channel, [filepath], titles=[title], initial_comment=initial_comment)


# ---------------------------------------------------------------
# Webhook notify (quiet)
# ---------------------------------------------------------------
def post_slack_webhook(message: str) -> bool:
    """
    Incoming Webhook に投稿。
    成功なら True。Webhook未設定なら False（=フォールバック可能）。
    """
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False

    try:
        r = requests.post(url, json={"text": message}, timeout=20)
        if r.status_code >= 400:
            print(f"[Slack] webhook failed: HTTP{r.status_code} {(r.text or '')[:200]}")
            return False
        print("[Slack] webhook notified")
        return True
    except Exception as e:
        print(f"[Slack] webhook exception: {type(e).__name__}: {e}")
        return False


def _notion_page_url(page_id: Optional[str]) -> str:
    if not page_id:
        return ""
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def notify_weather_delivery(
    *,
    category: str,
    page_id: Optional[str],
    errors: Optional[Sequence[str]] = None,
    attach_count: Optional[int] = None,
) -> None:
    """
    メール通知相当の粒度で「配信完了」を通知する。

    表示例:
    天気図配信
    区分: Weathercaster
    エラー: 0件
    Notion: https://www.notion.so/xxxx
    添付: 13件
    """
    errs = list(errors) if errors else []
    err_count = len(errs)

    lines = [
        "天気図配信",
        f"区分: {category}",
        f"エラー: {err_count}件" + (f" / {errs[0]}" if err_count else ""),
    ]

    if page_id:
        lines.append(f"Notion: {_notion_page_url(page_id)}")

    if attach_count is not None:
        lines.append(f"添付: {attach_count}件")

    msg = "\n".join(lines)

    # Webhook優先（チャンネルはWebhook側で #wx-python 固定）
    if post_slack_webhook(msg):
        return

    # Webhookが無い場合は Bot token でフォールバック
    send_slack_text_default(msg)
