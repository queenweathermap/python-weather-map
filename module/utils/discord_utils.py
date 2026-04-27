# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/discord_utils.py
#
# Discord Webhook 投稿ユーティリティ
#
# 役割:
#   - ADV / Weathercaster でチャンネルを分けて投稿
#   - 画像はR2 URLをDiscordにembed表示
#   - 最後にNotion URL付きの完了通知を出す
#
# Botは使わず、Webhookのみ使用。
# =============================================================================

from __future__ import annotations

import os
import time
from typing import List, Optional

import requests


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v.strip()


def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    v = _env(name)
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        return default


def discord_enabled(webhook_url: Optional[str] = None) -> bool:
    """
    Discord投稿のON/OFF判定。
    """
    enabled = _env("DISCORD_ENABLE", "0").lower() in ("1", "true", "yes", "on")

    if webhook_url is not None:
        return enabled and bool(webhook_url.strip())

    return enabled and bool(_env("DISCORD_WEBHOOK_URL"))


def _post_with_rate_limit(
    *,
    webhook_url: str,
    payload: dict,
    timeout: int = 60,
) -> requests.Response:
    """
    Discord Webhookへ投稿する。
    429が返ったら retry_after 秒だけ待って1回再送する。
    """
    if not webhook_url:
        raise RuntimeError("Discord webhook_url is missing")

    r = requests.post(webhook_url, json=payload, timeout=timeout)

    if r.status_code == 429:
        try:
            retry_after = float(r.json().get("retry_after", 1.0))
        except Exception:
            retry_after = 1.0

        print(f"[WARN] Discord rate limited. retry_after={retry_after}")
        time.sleep(retry_after)

        r = requests.post(webhook_url, json=payload, timeout=timeout)

    r.raise_for_status()
    return r


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    """
    Discord embedは1投稿10個までにする。
    """
    if size <= 0:
        size = 10

    return [
        items[i:i + size]
        for i in range(0, len(items), size)
    ]


def post_discord_item_image_urls(
    *,
    webhook_url: str,
    title: str,
    image_urls: List[str],
    notion_url: str = "",
    rjtd: str = "",
    init_jst: str = "",
    r2_folder_url: str = "",
) -> None:
    """
    item単位で画像URLをDiscordに投稿する。
    """
    if not discord_enabled(webhook_url):
        return

    if not image_urls:
        return

    max_images = _env_int("DISCORD_MAX_IMAGES_PER_MESSAGE", 10)
    sleep_sec = _env_float("DISCORD_SLEEP_SEC", 1.0)

    chunks = _chunk_list(image_urls, max_images)

    for idx, chunk in enumerate(chunks, start=1):
        lines = [f"🗺️ {title}"]

        if init_jst:
            lines.append(f"初期時刻: {init_jst}")

        if rjtd:
            lines.append(f"RJTD: {rjtd}")

        if notion_url:
            lines.append(f"Notion: {notion_url}")

        if r2_folder_url:
            lines.append(f"R2: {r2_folder_url}")

        if len(chunks) > 1:
            lines.append(f"分割: {idx}/{len(chunks)}")

        embeds = [{"image": {"url": url}} for url in chunk]

        payload = {
            "content": "\n".join(lines)[:1900],
            "embeds": embeds,
            "allowed_mentions": {"parse": []},
        }

        _post_with_rate_limit(
            webhook_url=webhook_url,
            payload=payload,
        )

        if idx < len(chunks):
            time.sleep(sleep_sec)


def post_discord_complete(
    *,
    webhook_url: str,
    category: str,
    notion_url: str = "",
    attach_count: int = 0,
    errors: Optional[List[str]] = None,
) -> None:
    """
    すべての処理が終わったあとに出す完了通知。

    ここにNotion URLを出す。
    """
    if not discord_enabled(webhook_url):
        return

    errors = errors or []

    if errors:
        error_text = f"{len(errors)}件 / " + " / ".join(errors[:3])
    else:
        error_text = "0件"

    lines = [
        "天気図配信",
        f"区分: {category}",
        f"エラー: {error_text}",
    ]

    if notion_url:
        lines.append(f"Notion: {notion_url}")

    lines.append(f"添付: {attach_count}件")

    payload = {
        "content": "\n".join(lines)[:1900],
        "allowed_mentions": {"parse": []},
    }

    _post_with_rate_limit(
        webhook_url=webhook_url,
        payload=payload,
    )
