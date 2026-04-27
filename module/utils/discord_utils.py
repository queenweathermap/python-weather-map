# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/discord_utils.py
#
# Discord Webhook 投稿ユーティリティ
#
# 目的:
#   - Discordを「画像ビューア」として使う
#   - Notionを正本、Discordを一覧表示・即時確認用にする
#   - Slack Botの代替として、完了通知もDiscordへ出す
#
# 設計:
#   - Botは使わない。Webhook URLだけで投稿する
#   - ADV と Weathercaster でチャンネルを分ける
#   - 画像は R2 URL を Discord embed で表示する
#   - 1投稿あたり最大10画像まで
#   - 最後に「完了通知」として Notion URL を投稿する
#
# Webhookの考え方:
#   ADV:
#     DISCORD_ADV_WEBHOOK_URL を優先
#
#   Weathercaster:
#     DISCORD_WEATHERCASTER_WEBHOOK_URL を優先
#
#   共通・予備:
#     DISCORD_WEBHOOK_URL
#
# 必須環境変数:
#   DISCORD_ENABLE=1
#
# 任意環境変数:
#   DISCORD_ADV_WEBHOOK_URL
#   DISCORD_WEATHERCASTER_WEBHOOK_URL
#   DISCORD_WEBHOOK_URL
#   DISCORD_MAX_IMAGES_PER_MESSAGE=10
#   DISCORD_SLEEP_SEC=1.0
#
# 重要:
#   - Discordは正本ではない
#   - 呼び出し元では try/except で囲み、Discord失敗で本処理を落とさない
# =============================================================================

from __future__ import annotations

import os
import time
from typing import List, Optional

import requests


# =============================================================================
# Environment helpers
# =============================================================================

def _env(name: str, default: str = "") -> str:
    """
    環境変数を安全に読む小さいヘルパー。
    None の場合は default を返す。
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


def discord_global_enabled() -> bool:
    """
    Discord投稿全体のON/OFF。

    DISCORD_ENABLE=1 / true / yes / on の場合だけ有効。
    """
    return _env("DISCORD_ENABLE", "0").lower() in ("1", "true", "yes", "on")


# =============================================================================
# Webhook helpers
# =============================================================================

def resolve_webhook_url(
    *,
    webhook_url: str = "",
    webhook_env: str = "",
) -> str:
    """
    Discord Webhook URLを決定する。

    優先順位:
      1. 引数 webhook_url
      2. 引数 webhook_env に指定された環境変数
      3. 共通 DISCORD_WEBHOOK_URL

    例:
      ADVなら webhook_env="DISCORD_ADV_WEBHOOK_URL"
      Weathercasterなら webhook_env="DISCORD_WEATHERCASTER_WEBHOOK_URL"
    """
    if webhook_url:
        return webhook_url.strip()

    if webhook_env:
        v = _env(webhook_env)
        if v:
            return v

    return _env("DISCORD_WEBHOOK_URL")


def discord_enabled(
    *,
    webhook_url: str = "",
    webhook_env: str = "",
) -> bool:
    """
    Discord投稿が可能かを判定する。

    条件:
      - DISCORD_ENABLE が true
      - 対象Webhook URLが存在する
    """
    if not discord_global_enabled():
        return False

    return bool(resolve_webhook_url(webhook_url=webhook_url, webhook_env=webhook_env))


def _post_with_rate_limit(
    *,
    payload: dict,
    webhook_url: str = "",
    webhook_env: str = "",
    timeout: int = 60,
) -> requests.Response:
    """
    Discord Webhookへ投稿する内部関数。

    Discordは短時間に連投すると 429 Too Many Requests を返す。
    その場合は retry_after 秒待って、1回だけ再投稿する。

    ここでは raise_for_status() する。
    呼び出し元の jma_adv.py / jma_weathercaster.py 側で try/except する。
    """
    url = resolve_webhook_url(webhook_url=webhook_url, webhook_env=webhook_env)

    if not url:
        raise RuntimeError("Discord webhook URL is missing")

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


# =============================================================================
# Common helpers
# =============================================================================

def notion_page_url_from_id(page_id: Optional[str]) -> str:
    """
    Notion page_id からブラウザで開けるURLを作る。

    Notion APIから返る page_id は
      xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    の形式。

    ブラウザURLはハイフン無しでも開ける。
    """
    if not page_id:
        return ""

    clean = page_id.replace("-", "").strip()
    if not clean:
        return ""

    return f"https://www.notion.so/{clean}"


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    """
    リストを size 件ずつ分割する。

    Discord embed は1投稿あたり最大10個までにしておく。
    """
    if size <= 0:
        size = 10

    return [
        items[i:i + size]
        for i in range(0, len(items), size)
    ]


def _safe_content(content: str, limit: int = 1900) -> str:
    """
    Discord本文は最大2000文字。
    余裕を持って1900文字で切る。
    """
    return (content or "").strip()[:limit]


# =============================================================================
# Image URL posting
# =============================================================================

def post_discord_item_image_urls(
    *,
    title: str,
    image_urls: List[str],
    webhook_env: str = "",
    webhook_url: str = "",
    notion_url: str = "",
    rjtd: str = "",
    init_jst: str = "",
    r2_folder_url: str = "",
) -> None:
    """
    item単位で Discord に画像URLを投稿する。

    ADV:
      - GSM / 300hPa
      - MSM / 500hPa
      のような item ごとの投稿に使う。

    Weathercaster:
      - 全画像をまとめて投稿する時にも使える。

    Parameters
    ----------
    title:
        投稿タイトル。
        例: ADV TGV GSM / 300hPa

    image_urls:
        R2にアップロード済みの画像URL一覧。
        JOIN_TRIPLE済み画像のURLを入れる。

    webhook_env:
        投稿先Webhookの環境変数名。
        例: DISCORD_ADV_WEBHOOK_URL

    notion_url:
        基本は完了通知にだけ出す想定。
        必要ならitem投稿にも表示可能。

    rjtd:
        RJTD文字列。

    init_jst:
        初期時刻JSTの表示用文字列。

    r2_folder_url:
        将来的にR2側の代表URLやフォルダURLを出したい場合の余地。
    """
    if not discord_enabled(webhook_url=webhook_url, webhook_env=webhook_env):
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
            "content": _safe_content("\n".join(lines)),
            "embeds": embeds,
            # @everyone 等の事故防止
            "allowed_mentions": {
                "parse": []
            },
        }

        _post_with_rate_limit(
            payload=payload,
            webhook_url=webhook_url,
            webhook_env=webhook_env,
        )

        if idx < len(chunks):
            time.sleep(sleep_sec)


# =============================================================================
# Completion notification
# =============================================================================

def post_discord_delivery_complete(
    *,
    category: str,
    notion_url: str,
    attach_count: int,
    errors: List[str],
    webhook_env: str = "",
    webhook_url: str = "",
    title: str = "天気図配信",
) -> None:
    """
    配信完了通知をDiscordへ投稿する。

    これはSlackで行っていた
      - 区分
      - エラー件数
      - Notion URL
      - 添付枚数
    の代替。

    重要:
      - すべての画像アップロード
      - Notion本文への画像追加
      が終わった後に呼ぶ。
    """
    if not discord_enabled(webhook_url=webhook_url, webhook_env=webhook_env):
        return

    if errors:
        # エラーが多すぎるとDiscord本文が長くなるので先頭数件だけ表示
        shown = errors[:5]
        error_text = f"{len(errors)}件 / " + " / ".join(shown)
        if len(errors) > len(shown):
            error_text += f" / ほか{len(errors) - len(shown)}件"
    else:
        error_text = "0件"

    lines = [
        title,
        f"区分: {category}",
        f"エラー: {error_text}",
    ]

    if notion_url:
        lines.append(f"Notion: {notion_url}")

    lines.append(f"添付: {attach_count}件")

    payload = {
        "content": _safe_content("\n".join(lines)),
        "allowed_mentions": {
            "parse": []
        },
    }

    _post_with_rate_limit(
        payload=payload,
        webhook_url=webhook_url,
        webhook_env=webhook_env,
    )
