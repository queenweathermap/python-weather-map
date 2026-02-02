# -*- coding: utf-8 -*-
"""
module/utils/notion_utils.py

Notion データベースに「天気図アーカイブ」を自動追加するユーティリティ。

環境変数:
- NOTION_TOKEN
- NOTION_DATABASE_ID

Notion 側のDBプロパティ例（推奨）
- Name (title)             : タイトル（例 "2026-02-02 GSM item01"）
- Date (date)              : 日付
- Model (select)           : GSM/MSM/LFM
- Item (rich_text or select): item名（例 "850hPa", "SURF" など）
- FT (number or rich_text) : 予報時間
- Map (files)              : Files & media（external url で画像表示）
- URL (url)                : 画像URLを別途保存しておく場合
- Status (select)          : ok / partial / error など任意

※ DB側のプロパティ名はあなたの運用に合わせて変えてOK。
   変更したらこのコード内のキーも合わせてください。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

from notion_client import Client


@dataclass
class NotionConfig:
    token: str
    database_id: str


def load_notion_config() -> NotionConfig:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    dbid = os.environ.get("NOTION_DATABASE_ID", "").strip()

    missing = []
    if not token:
        missing.append("NOTION_TOKEN")
    if not dbid:
        missing.append("NOTION_DATABASE_ID")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return NotionConfig(token=token, database_id=dbid)


def _client() -> Client:
    cfg = load_notion_config()
    return Client(auth=cfg.token)


def create_weather_page(
    *,
    title: str,
    date_iso: str,
    model: str,
    item: str,
    ft: str,
    image_url: str,
    status: str = "ok",
    extra_props: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Notion DBに1行追加（画像 external URL を Files&media に入れる）
    """
    cfg = load_notion_config()
    notion = _client()

    props: Dict[str, Any] = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Date": {"date": {"start": date_iso}},
        "Model": {"select": {"name": model}},
        "Item": {"rich_text": [{"text": {"content": item}}]},
        "FT": {"rich_text": [{"text": {"content": str(ft)}}]},
        "Map": {
            "files": [
                {
                    "name": title,
                    "external": {"url": image_url},
                }
            ]
        },
        "URL": {"url": image_url},
        "Status": {"select": {"name": status}},
    }

    if extra_props:
        props.update(extra_props)

    return notion.pages.create(
        parent={"database_id": cfg.database_id},
        properties=props,
    )


def is_notion_enabled() -> bool:
    """
    NOTION_TOKEN/DBIDが無ければNotion投稿をスキップできるようにする。
    """
    return bool(os.environ.get("NOTION_TOKEN", "").strip() and os.environ.get("NOTION_DATABASE_ID", "").strip())
