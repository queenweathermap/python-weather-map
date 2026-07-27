# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/discord_dm.py
#
# 有料DM配信: Discord Bot経由で個別ユーザーへDMを送る。
# Webhookと違い、BotはあらかじめDiscordサーバーで購読者と同じサーバーを
# 共有している必要がある（サーバー参加はCloudflare Worker側のOAuthフローで
# 済ませている前提）。
#
# 必要な環境変数
#   DISCORD_BOT_TOKEN
# =============================================================================

from __future__ import annotations

import json
import os
import sys

import requests

API_BASE = "https://discord.com/api/v10"
REQUEST_TIMEOUT_SECONDS = 30


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def _headers() -> dict:
    return {"Authorization": f"Bot {_must_env('DISCORD_BOT_TOKEN')}"}


def _open_dm_channel(discord_user_id: str) -> str | None:
    try:
        r = requests.post(
            f"{API_BASE}/users/@me/channels",
            headers={**_headers(), "Content-Type": "application/json"},
            json={"recipient_id": discord_user_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        print(f"ERROR: DMチャンネル作成中に例外 ({discord_user_id}): {exc}", file=sys.stderr)
        return None

    if r.status_code not in (200, 201):
        print(f"ERROR: DMチャンネル作成失敗 ({discord_user_id}) status={r.status_code} body={r.text[:300]}", file=sys.stderr)
        return None

    return r.json().get("id")


def send_dm(discord_user_id: str, content: str, image_bytes: bytes, filename: str) -> bool:
    """指定ユーザーへ、テキスト内容＋画像添付のDMを送る。"""
    channel_id = _open_dm_channel(discord_user_id)
    if not channel_id:
        return False

    files = {
        "payload_json": (None, json.dumps({"content": content})),
        "files[0]": (filename, image_bytes, "image/jpeg" if filename.endswith((".jpg", ".jpeg")) else "image/png"),
    }

    try:
        r = requests.post(
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=_headers(),
            files=files,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        print(f"ERROR: DM送信中に例外 ({discord_user_id}): {exc}", file=sys.stderr)
        return False

    if 200 <= r.status_code < 300:
        return True

    print(f"ERROR: DM送信失敗 ({discord_user_id}) status={r.status_code} body={r.text[:300]}", file=sys.stderr)
    return False


def send_dm_to_all(discord_user_ids: list, content: str, image_bytes: bytes, filename: str) -> None:
    """購読者全員へ順にDMする。1件の失敗が全体を止めないようにする。"""
    for discord_user_id in discord_user_ids:
        ok = send_dm(discord_user_id, content, image_bytes, filename)
        print(f"DM {'OK' if ok else 'FAILED'}: {discord_user_id}")
