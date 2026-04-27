# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/discord_utils.py
#
# Discord Webhook 投稿ユーティリティ
#
# 目的:
#   - Discordを「画像ビューア」として使う
#   - Notionを正本、Discordを一覧表示・確認用にする
#
# 特徴:
#   - Bot作成不要。Webhook URLだけで投稿可能
#   - 画像を複数枚まとめて送信
#   - 1投稿あたりの枚数を制限して分割投稿
#   - レート制限 429 が返ったら retry_after を見て待つ
#
# 必要な環境変数:
#   DISCORD_WEBHOOK_URL
#
# 任意:
#   DISCORD_ENABLE=1
#   DISCORD_MAX_FILES_PER_MESSAGE=10
#   DISCORD_SLEEP_SEC=1.0
#
# 注意:
#   - Discordの無料アップロード上限は 10MB/ファイルが目安
#   - ADVは枚数が多いので、itemごと投稿が安全
#   - Notionに全部保存し、Discordには見やすい単位で流す設計
# =============================================================================

from __future__ import annotations

import json
import os
import time
from typing import List, Tuple, Optional

import requests


# 添付画像の型
# filename: Discordに表示されるファイル名
# blob:     画像バイナリ
# mimetype: image/jpeg など
Attachment = Tuple[str, bytes, str]


def _env(name: str, default: str = "") -> str:
    """
    環境変数を安全に読む小さいヘルパー。
    Noneの場合は default を返す。
    """
    v = os.environ.get(name)
    return default if v is None else v.strip()


def _env_int(name: str, default: int) -> int:
    """
    int型の環境変数を読む。
    壊れていたら default。
    """
    v = _env(name)
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    """
    float型の環境変数を読む。
    壊れていたら default。
    """
    v = _env(name)
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        return default


def discord_enabled() -> bool:
    """
    Discord投稿を有効にするか判定。
    DISCORD_ENABLE=1 かつ DISCORD_WEBHOOK_URL がある時だけ True。
    """
    enabled = _env("DISCORD_ENABLE", "0").lower() in ("1", "true", "yes", "on")
    webhook = bool(_env("DISCORD_WEBHOOK_URL"))
    return enabled and webhook


def _webhook_url() -> str:
    """
    Discord Webhook URLを取得。
    """
    return _env("DISCORD_WEBHOOK_URL")


def _post_with_rate_limit(
    *,
    data: Optional[dict] = None,
    json_body: Optional[dict] = None,
    files: Optional[dict] = None,
    timeout: int = 120,
) -> requests.Response:
    """
    Discord WebhookへPOSTする内部関数。

    Discordは短時間に連投すると 429 Too Many Requests を返すことがあります。
    その場合、レスポンスJSONに retry_after が入るので、その秒数だけ待って再送します。
    """
    url = _webhook_url()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")

    r = requests.post(
        url,
        data=data,
        json=json_body,
        files=files,
        timeout=timeout,
    )

    if r.status_code == 429:
        try:
            retry_after = float(r.json().get("retry_after", 1.0))
        except Exception:
            retry_after = 1.0

        print(f"[WARN] Discord rate limited. retry_after={retry_after}")
        time.sleep(retry_after)

        r = requests.post(
            url,
            data=data,
            json=json_body,
            files=files,
            timeout=timeout,
        )

    r.raise_for_status()
    return r


def post_discord_text(content: str) -> None:
    """
    Discordへテキストだけ投稿する。

    Discordの通常メッセージは最大2000文字なので、
    長い場合は安全に切る。
    """
    if not discord_enabled():
        return

    content = (content or "").strip()
    if not content:
        return

    _post_with_rate_limit(
        json_body={"content": content[:2000]},
        timeout=60,
    )


def _chunk_attachments(
    files: List[Attachment],
    max_files_per_message: int,
) -> List[List[Attachment]]:
    """
    添付ファイル配列を max_files_per_message ごとに分割する。
    """
    if max_files_per_message <= 0:
        max_files_per_message = 10

    return [
        files[i:i + max_files_per_message]
        for i in range(0, len(files), max_files_per_message)
    ]


def post_discord_files(
    *,
    content: str,
    files: List[Attachment],
    max_files_per_message: Optional[int] = None,
    sleep_sec: Optional[float] = None,
) -> None:
    """
    Discordへ画像ファイルを投稿する。

    Parameters
    ----------
    content:
        メッセージ本文。
        1投稿目に主に表示する。
        続き投稿では「続き n」を付ける。

    files:
        (filename, bytes, mimetype) の配列。

    max_files_per_message:
        1投稿あたりの最大添付数。
        Discord運用上、10枚にしておくのが安全。

    sleep_sec:
        連続投稿間の待ち時間。
        ADVは枚数が多いので 1秒程度入れると安定。
    """
    if not discord_enabled():
        return

    if not files:
        return

    max_files = max_files_per_message or _env_int("DISCORD_MAX_FILES_PER_MESSAGE", 10)
    wait = sleep_sec if sleep_sec is not None else _env_float("DISCORD_SLEEP_SEC", 1.0)

    chunks = _chunk_attachments(files, max_files)

    for idx, chunk in enumerate(chunks, start=1):
        # Discord multipart投稿では payload_json に本文を入れる。
        # files[n] に画像本体を入れる。
        if idx == 1:
            msg = content[:1900]
        else:
            msg = f"{content[:1750]}\n（続き {idx}/{len(chunks)}）"

        payload = {
            "content": msg,
            # メンション事故防止。@everyone等を無効化。
            "allowed_mentions": {"parse": []},
        }

        multipart_files = {}
        for file_index, (fname, blob, mimetype) in enumerate(chunk):
            multipart_files[f"files[{file_index}]"] = (fname, blob, mimetype)

        _post_with_rate_limit(
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files=multipart_files,
            timeout=120,
        )

        # 連投時の安全待機
        if idx < len(chunks):
            time.sleep(wait)


def post_discord_item_images(
    *,
    title: str,
    attachments: List[Attachment],
    notion_url: str = "",
    rjtd: str = "",
) -> None:
    """
    ADVの item 単位投稿向けヘルパー。

    例:
        title = "ADV TGV GSM / 300hPa"
        attachments = atts

    Discordには item ごとに流すのがおすすめ。
    理由:
        - 画像枚数が多すぎるとチャンネルが読みにくくなる
        - itemごとのまとまりならスクロールで追いやすい
        - 10枚ずつ分割投稿しやすい
    """
    if not discord_enabled():
        return

    lines = [f"🗺️ {title}"]

    if rjtd:
        lines.append(f"RJTD: {rjtd}")

    if notion_url:
        lines.append("")
        lines.append(f"Notion: {notion_url}")

    content = "\n".join(lines)

    post_discord_files(
        content=content,
        files=attachments,
    )
