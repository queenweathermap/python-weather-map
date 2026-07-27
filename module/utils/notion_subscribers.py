# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_subscribers.py
#
# 有料DM配信の購読者リスト（Notionデータベース）を読むユーティリティ。
# 書き込み（行の作成・更新）はCloudflare Worker側（Stripe Webhook）が行うため、
# ここでは読み取り専用。
#
# Status の種類:
#   active  ... Stripe課金中
#   beta    ... 無料のβtester（BETA_CUTOFFを過ぎたら自動的に配信対象から外れる）
#   admin   ... 運営者自身。課金なしで常に配信対象
#   canceled... 配信対象外
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
from datetime import datetime, timezone, timedelta
from typing import List

import requests

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"

# 本格運用（課金必須）の開始日。Worker側 (src/index.ts) の BETA_CUTOFF と同じ日付。
JST = timezone(timedelta(hours=9))
BETA_CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=JST)

ELIGIBLE_STATUSES = ("active", "beta", "admin")


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
    """購読者データベースから配信対象（active/beta/admin）のDiscord User IDを返す。
    ただしbetaはBETA_CUTOFFを過ぎたら対象外にする（Notion側のStatusは
    手動更新不要で、ここでの日付判定だけで自動的に配信が止まる）。"""
    db_id = _must_env("NOTION_SUBSCRIBERS_DATABASE_ID")

    payload = {
        "filter": {
            "or": [
                {"property": _prop_status(), "select": {"equals": status}}
                for status in ELIGIBLE_STATUSES
            ]
        },
        "page_size": 100,
    }

    beta_still_open = datetime.now(JST) < BETA_CUTOFF

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

            status = (props.get(_prop_status(), {}).get("select") or {}).get("name", "")
            if status == "beta" and not beta_still_open:
                continue

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
