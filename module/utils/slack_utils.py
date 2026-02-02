# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/slack_utils.py
# =============================================================================
# Slack通知＆ファイルアップロードユーティリティ（外部アップロード3-step対応）
#
# 目的:
#   - エラー通知（chat.postMessage）
#   - 画像（JPG/PNG）やPDFなどのファイルをチャンネルに投稿
#   - ADV JMA の生成物（bytes）をそのまま Slack に投げたい用途に対応
#
# 前提:
#   - SLACK_BOT_TOKEN を環境変数で渡す（GitHub Actions secrets など）
#   - チャンネルは「名前」ではなく「チャンネルID」（例: C0123...）を使う
#   - Botがそのチャンネルに招待されていること
#   - Bot Token Scopes に files:write / chat:write が付与されていること
#
# 実装方針:
#   - ファイル送信は Slack推奨の「外部アップロード」3ステップ
#       1) files.getUploadURLExternal
#       2) upload_url へ PUT（バイナリ本体）
#       3) files.completeUploadExternal（channel_id + initial_comment + files）
#
# 注意:
#   - Slack側仕様変更や権限不足で失敗しやすいので、失敗時ログを厚めに出す
# =============================================================================

from __future__ import annotations

import os
import re
import tempfile
from typing import Sequence, Optional, List, Tuple

import requests


# =============================================================================
# 基本設定
# =============================================================================
SLACK_API_BASE = "https://slack.com/api"

# Slackの投稿本文は長すぎると落ちることがあるので、安全側に短くする
# （chat.postMessage はもっと長いが、他APIやUI反映で詰まる例があるため）
MAX_COMMENT_LEN = 3500


# =============================================================================
# Helpers
# =============================================================================
def sanitize_filename(filename: str) -> str:
    """
    Slackファイルアップロード用にファイル名をサニタイズ
    （半角英数字・アンダースコア・ピリオド・ハイフン以外は '_' へ）
    """
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)


def _shorten_comment(text: str) -> str:
    """
    Slack投稿用コメントを安全に短縮
    """
    if not text:
        return ""
    t = text.strip()
    if len(t) <= MAX_COMMENT_LEN:
        return t
    return t[: MAX_COMMENT_LEN - 3] + "..."


def get_slack_token() -> Optional[str]:
    """
    Bot Token を環境変数から取得
    """
    return os.environ.get("SLACK_BOT_TOKEN")


def _auth_headers(token: str) -> dict:
    """
    Slack Web API 用 Authorization ヘッダ
    """
    return {"Authorization": f"Bearer {token}"}


def _print_slack_api_error(prefix: str, *, http_status: int, body_text: str, json_obj: Optional[dict] = None) -> None:
    """
    Slack API 失敗時のログ（原因追跡用）
    """
    head = (body_text or "")[:500]
    print(f"[ERROR] {prefix} (HTTP {http_status})")
    if json_obj is not None:
        # ok=false の時、error が入る
        print(f"        slack_error={json_obj.get('error')}")
        # たまに required_scope / provided などの情報が入ることがある
        for k in ("needed", "provided", "warning"):
            if k in json_obj:
                print(f"        {k}={json_obj.get(k)}")
    print(f"        response_head={head}")


# =============================================================================
# Text message
# =============================================================================
def send_slack_text(channel: str, message: str) -> None:
    """
    指定チャンネルにテキストメッセージを送信（chat.postMessage API）

    用途:
      - エラー通知、重要ログなど
      - ADV運用では「成功時は送らない / 失敗時だけ送る」でもOK
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です（send_slack_text をスキップ）")
        return

    url = f"{SLACK_API_BASE}/chat.postMessage"
    payload = {"channel": channel, "text": _shorten_comment(message)}
    try:
        res = requests.post(url, headers=_auth_headers(bot_token), json=payload, timeout=30)
    except Exception as e:
        print(f"[ERROR] Slack chat.postMessage リクエスト失敗: {e}")
        return

    # Slack Web API は 200でも ok=false がある
    try:
        j = res.json()
    except Exception:
        _print_slack_api_error("chat.postMessage JSON decode failed", http_status=res.status_code, body_text=res.text)
        return

    if not j.get("ok"):
        _print_slack_api_error("chat.postMessage failed", http_status=res.status_code, body_text=res.text, json_obj=j)
        return

    print(f"[Slack] メッセージ送信完了: {payload['text'][:40]}...")


# =============================================================================
# File upload (external upload 3-step)
# =============================================================================
def upload_files_slack(
    channel: str,
    filepaths: List[str],
    *,
    titles: Optional[List[str]] = None,
    initial_comment: str = "",
) -> None:
    """
    複数ファイルを「1つの投稿」に束ねてアップロード（外部アップロード 3-step）

    Args:
      channel: チャンネルID（例: C0123...）
      filepaths: 送るローカルファイルパスの配列
      titles: Slack上での表示タイトル（省略可）
      initial_comment: 投稿本文（省略可）

    Notes:
      - titles は filepaths と同じ順序で対応させる
      - ファイルが存在しない / サイズ0 はスキップ
      - 全部スキップされたら何もしない
    """
    bot_token = get_slack_token()
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が未設定です（upload_files_slack をスキップ）")
        return

    headers = _auth_headers(bot_token)
    files_meta: List[dict] = []  # [{"id": file_id, "title": "..."}]

    # ---- Step1 + Step2 をファイルごとに回す ----
    for idx, p in enumerate(filepaths):
        if not os.path.exists(p):
            print(f"[WARN] ファイルが見つかりません: {p}")
            continue

        # Slackに渡す filename は basename 推奨
        filename = sanitize_filename(os.path.basename(p))
        length = os.path.getsize(p)

        if length <= 0:
            print(f"[WARN] サイズ0のためスキップ: {p}")
            continue

        # --------------------------
        # Step 1: getUploadURLExternal
        # --------------------------
        url1 = f"{SLACK_API_BASE}/files.getUploadURLExternal"
        payload1 = {"filename": filename, "length": length}
        try:
            r1 = requests.post(url1, headers=headers, json=payload1, timeout=60)
        except Exception as e:
            print(f"[ERROR] getUploadURLExternal リクエスト失敗: {e}")
            continue

        try:
            j1 = r1.json()
        except Exception:
            _print_slack_api_error("getUploadURLExternal JSON decode failed", http_status=r1.status_code, body_text=r1.text)
            continue

        if not j1.get("ok"):
            _print_slack_api_error("getUploadURLExternal failed", http_status=r1.status_code, body_text=r1.text, json_obj=j1)
            continue

        upload_url = j1["upload_url"]
        file_id = j1["file_id"]

        # --------------------------
        # Step 2: upload_url へ PUT（生データ）
        # --------------------------
        try:
            with open(p, "rb") as f:
                r2 = requests.put(
                    upload_url,
                    data=f,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=300,
                )
        except Exception as e:
            print(f"[ERROR] PUT(upload_url) 失敗: {e}")
            continue

        if r2.status_code != 200:
            # upload_url は Slack API ではなくストレージURLなので、レスポンス形式が違う
            print(f"[ERROR] PUT 失敗: HTTP {r2.status_code} head={(r2.text or '')[:200]}")
            continue

        # 投稿時の表示タイトル
        title = titles[idx] if titles and idx < len(titles) else filename
        files_meta.append({"id": file_id, "title": title})

    if not files_meta:
        print("[WARN] アップロード対象がありませんでした（全スキップ）")
        return

    # --------------------------
    # Step 3: completeUploadExternal
    # --------------------------
    url3 = f"{SLACK_API_BASE}/files.completeUploadExternal"
    payload3 = {
        "channel_id": channel,
        "initial_comment": _shorten_comment(initial_comment),
        "files": files_meta,
    }

    try:
        r3 = requests.post(url3, headers=headers, json=payload3, timeout=60)
    except Exception as e:
        print(f"[ERROR] completeUploadExternal リクエスト失敗: {e}")
        return

    try:
        j3 = r3.json()
    except Exception:
        _print_slack_api_error("completeUploadExternal JSON decode failed", http_status=r3.status_code, body_text=r3.text)
        return

    if not j3.get("ok"):
        _print_slack_api_error("completeUploadExternal failed", http_status=r3.status_code, body_text=r3.text, json_obj=j3)
        return

    print(f"[Slack] ファイル {len(files_meta)}件を1投稿で送信しました")


# =============================================================================
# Bytes uploader (bridge for ADV script)
# =============================================================================
def upload_bytes_slack(
    channel: str,
    files: Sequence[Tuple[str, bytes]],
    *,
    initial_comment: str = "",
    titles: Optional[Sequence[str]] = None,
) -> None:
    """
    (filename, bytes) を受け取り、一時ファイルに書いて upload_files_slack() で送る。

    用途:
      - scripts/jma_adv.py の「生成した JPG bytes」を直接 Slack に投げる
      - 生成物がメモリ上にあるまま送信したい時に便利

    Args:
      channel: チャンネルID（例: C0123...）
      files: [(filename, blob), ...]
      initial_comment: Slackの投稿本文
      titles: Slack上の表示タイトル（省略可）
    """
    tmp_paths: List[str] = []

    try:
        for i, (name, blob) in enumerate(files):
            safe = sanitize_filename(name)

            # 拡張子はできるだけ維持（Slack UI の判定に効くことがある）
            suffix = os.path.splitext(safe)[1] or ".bin"

            # NamedTemporaryFile(delete=False) にして、後で明示削除する
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
                tf.write(blob)
                tmp_paths.append(tf.name)

        upload_files_slack(
            channel=channel,
            filepaths=tmp_paths,
            titles=list(titles) if titles is not None else None,
            initial_comment=initial_comment,
        )

    finally:
        # 一時ファイルは必ず掃除
        for p in tmp_paths:
            try:
                os.remove(p)
            except Exception:
                pass


# =============================================================================
# Compatibility wrapper (single file)
# =============================================================================
def upload_file_slack(
    channel: str,
    filepath: str,
    *,
    title: str = "Weather Map",
    initial_comment: str = "Here is the latest weather map!",
) -> None:
    """
    単発アップロードは upload_files_slack() のラッパーに統一
    （二重実装による修正漏れ事故を防ぐ）
    """
    upload_files_slack(channel, [filepath], titles=[title], initial_comment=initial_comment)
