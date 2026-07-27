# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_subscribers.py
#
# 有料DM配信の購読者リスト（Notionデータベース）を読むユーティリティ。
# 書き込み（行の作成・更新）はCloudflare Worker側（Stripe Webhook）が行うため、
# ここでは読み取り専用（Status=active の Discord User ID一覧を返す）。
#
# 必要な環境変数
#   NOTION_TOKEN                    （module/utils/notion_utils.py と共有）
#   NOTION_SUBSCRIBERS_DATABASE_ID
#
# 任意（DBプロパティ名が環境で違う場合の上書き）
#   NOTION_SUB_PROP_STATUS="Status"
#   NOTION_SUB_PROP_DISCORD_ID="Discord User ID"
# =============================================================================

from __future__ import annotations

import os
from typing import List

import requests

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"

ACTIVE_STATUS = "active"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_must_env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _prop_status() -> str:
    return _env("NOTION_SUB_PROP_STATUS", "Status")


def _prop_discord_id() -> str:
    return _env("NOTION_SUB_PROP_DISCORD_ID", "Discord User ID")


def get_active_discord_ids() -> List[str]:
    """購読者データベースから Status=active のDiscord User IDを全件返す。"""
    db_id = _must_env("NOTION_SUBSCRIBERS_DATABASE_ID")

    payload = {
        "filter": {
            "property": _prop_status(),
            "select": {"equals": ACTIVE_STATUS},
        },
        "page_size": 100,
    }

    ids: List[str] = []
    cursor = None

    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor

        r = requests.post(
            f"{API_BASE}/databases/{db_id}/query",
            headers=_headers(),
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

        for page in data.get("results", []):
            props = page.get("properties", {})
            rich_text = props.get(_prop_discord_id(), {}).get("rich_text", [])
            if rich_text:
                discord_id = rich_text[0].get("plain_text", "").strip()
                if discord_id:
                    ids.append(discord_id)

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    return ids
