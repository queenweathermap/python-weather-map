# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_utils.py
#
# Notion API ユーティリティ（外部URLの画像を埋め込み）
# - create_run_page(): 親ページ配下に「実行ページ」を作る
# - append_heading(): 見出しを追加
# - append_images(): 外部URL画像を並べる（Notion側で埋め込み表示）
#
# 必要な環境変数
#   NOTION_TOKEN
#   NOTION_PARENT_PAGE_ID
#
# 任意
#   NOTION_ENABLE=1         # 0なら何もしない（テスト用）
# =============================================================================

from __future__ import annotations

import os
import requests
from typing import List, Optional


NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def notion_enabled() -> bool:
    v = _env("NOTION_ENABLE", "1").lower()
    return v in ("1", "true", "yes", "on")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_must_env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def create_run_page(title: str, *, icon_emoji: str = "🗺️") -> Optional[str]:
    """
    親ページ配下に新規ページを作成して page_id を返す
    """
    if not notion_enabled():
        return None

    parent_id = _must_env("NOTION_PARENT_PAGE_ID")

    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "icon": {"type": "emoji", "emoji": icon_emoji},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
    }

    r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def append_heading(page_id: str, text: str, *, level: int = 2) -> None:
    """
    見出しブロック（heading_2 / heading_3）を追加
    """
    if not notion_enabled():
        return

    if level not in (2, 3):
        level = 2
    t = "heading_2" if level == 2 else "heading_3"

    payload = {
        "children": [
            {
                "object": "block",
                "type": t,
                t: {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                },
            }
        ]
    }

    r = requests.patch(f"{API_BASE}/blocks/{page_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()


def append_images(page_id: str, urls: List[str], *, chunk: int = 50) -> None:
    """
    外部URL画像を Notionページに埋め込みで追加。
    Notion APIは一度に大量のblocksを投げると落ちやすいので chunk 分割。
    """
    if not notion_enabled():
        return

    urls = [u for u in urls if u]
    if not urls:
        return

    for i in range(0, len(urls), chunk):
        part = urls[i:i + chunk]
        children = []
        for u in part:
            children.append(
                {
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": u},
                    },
                }
            )

        payload = {"children": children}
        r = requests.patch(f"{API_BASE}/blocks/{page_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()
