# -*- coding: utf-8 -*-
# module/utils/notion_utils.py
"""
Notion DBにページ作成して、外部画像URLを埋め込む
"""

import os
from datetime import datetime
from typing import List

from notion_client import Client


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _must(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


def notion_client() -> Client:
    return Client(auth=_must("NOTION_TOKEN"))


def create_run_page(title: str) -> str:
    """
    Notion DBにページを作る。返り値は page_id。
    DB側に title property が必要（Name等でもOKだがここは title を想定）
    """
    db_id = _must("NOTION_DATABASE_ID")
    cli = notion_client()

    res = cli.pages.create(
        parent={"database_id": db_id},
        properties={
            "title": {
                "title": [{"text": {"content": title}}]
            }
        },
    )
    return res["id"]


def append_images(page_id: str, urls: List[str], caption_prefix: str = "") -> None:
    """
    画像URLをページ末尾に追加する
    """
    cli = notion_client()

    blocks = []
    for i, u in enumerate(urls, start=1):
        cap = f"{caption_prefix}{i}" if caption_prefix else ""
        blocks.append(
            {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": u},
                    "caption": [{"type": "text", "text": {"content": cap}}] if cap else [],
                },
            }
        )

    # 100ブロック制限があるので分割
    chunk = 50
    for j in range(0, len(blocks), chunk):
        cli.blocks.children.append(
            block_id=page_id,
            children=blocks[j:j + chunk],
        )
