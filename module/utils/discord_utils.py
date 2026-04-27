# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/discord_utils.py
#
# Discord Webhook 投稿ユーティリティ
#
# 目的:
#   - Discordを「画像ビューア」として使う
#   - Notionを正本、Discordを一覧表示・即時確認用にする
#
# 設計:
#   - Botは使わない。Webhook URLだけで投稿する
#   - ADVは item ごとに投稿する
#   - 画像は R2 URL を embed 表示する
#   - 1投稿あたり最大10画像まで
#   - Discord投稿に失敗しても、呼び出し元で握りつぶせるようにする
#
# 必須環境変数:
#   DISCORD_WEBHOOK_URL
#
# 任意環境変数:
#   DISCORD_ENABLE=1
#   DISCORD_MAX_IMAGES_PER_MESSAGE=10
#   DISCORD_SLEEP_SEC=1.0
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


def discord_enabled() -> bool:
    """
    Discord投稿を有効にするか判定する。

    DISCORD_ENABLE=1
    かつ
    DISCORD_WEBHOOK_URL が存在する

    この両方を満たす場合のみ True。
    """
    enabled = _env("DISCORD_ENABLE", "0").lower() in ("1", "true", "yes", "on")
    webhook = bool(_env("DISCORD_WEBHOOK_URL"))
    return enabled and webhook


def _webhook_url() -> str:
    url = _env("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")
    return url


def _post_with_rate_limit(payload: dict, timeout: int = 60) -> requests.Response:
    """
    Discord Webhookへ投稿する内部関数。

    Discordは短時間に連投すると 429 Too Many Requests を返す。
    その場合は retry_after 秒待って、1回だけ再投稿する。
    """
    url = _webhook_url()

    r = requests.post(url, json=payload, timeout=timeout)

    if r.status_code == 429:
        try:
            retry_after = float(r.json().get("retry_after", 1.0))
        except Exception:
            retry_after = 1.0

        print(f"[WARN] Discord rate limited. retry_after={retry_after}")
        time.sleep(retry_after)

        r = requests.post(url, json=payload, timeout=timeout)

    r.raise_for_status()
    return r


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    """
    リストを size 件ずつ分割する。
    Discord embed は1投稿10個までにしておく。
    """
    if size <= 0:
        size = 10

    return [
        items[i:i + size]
        for i in range(0, len(items), size)
    ]


def post_discord_item_image_urls(
    *,
    title: str,
    image_urls: List[str],
    notion_url: str = "",
    rjtd: str = "",
    init_jst: str = "",
    r2_folder_url: str = "",
) -> None:
    """
    ADV item 単位で Discord に画像URLを投稿する。

    Parameters
    ----------
    title:
        投稿タイトル。
        例: ADV TGV GSM / 300hPa

    image_urls:
        R2にアップロード済みの画像URL一覧。
        JOIN_TRIPLE済み画像のURLを入れる。

    notion_url:
        後でNotionページURLを渡せるようにしておく。
        今は空でもOK。

    rjtd:
        RJTD文字列。
        例: 270000

    init_jst:
        初期時刻JSTの表示用文字列。

    r2_folder_url:
        将来的にR2側の代表URLやフォルダ相当URLを入れたい場合の余地。
    """
    if not discord_enabled():
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

        content = "\n".join(lines)

        embeds = []
        for image_url in chunk:
            embeds.append(
                {
                    "image": {
                        "url": image_url,
                    }
                }
            )

        payload = {
            "content": content[:1900],
            "embeds": embeds,
            "allowed_mentions": {
                "parse": []
            },
        }

        _post_with_rate_limit(payload)

        if idx < len(chunks):
            time.sleep(sleep_sec)
