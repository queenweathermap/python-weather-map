# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_utils.py
#
# Notion API ユーティリティ
# - 旧: 親ページ配下に「実行ページ」を作る（create_run_page）
# - 新: DBに「実行レコード（=ページ）」を作る（create_db_run_page）
# - append_heading(): 見出しを追加
# - append_images(): 外部URL画像を並べる（埋め込み表示）
# - append_image(): 画像1枚
# - append_toggle_images(): toggle（開閉）ブロック配下に画像を入れる（全文画像用）
#
# 必要な環境変数
#   NOTION_TOKEN
#
# DB運用（本命）
#   NOTION_DATABASE_ID
#
# 旧ページ運用（互換）
#   NOTION_PARENT_PAGE_ID
#
# 任意
#   NOTION_ENABLE=1         # 0なら何もしない（テスト用）
# =============================================================================

from __future__ import annotations

import os
import requests
from typing import List, Optional, Dict, Any


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


# =============================================================================
# 旧: 親ページ配下に「実行ページ」を作る（互換）
# =============================================================================
def create_run_page(title: str, *, icon_emoji: str = "🗺️") -> Optional[str]:
    """
    親ページ配下に新規ページを作成して page_id を返す（旧方式）
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


# =============================================================================
# 新: DBに「実行レコード（=ページ）」を作る（本命）
# =============================================================================
def create_db_run_page(
    title: str,
    *,
    icon_emoji: str = "🗺️",
    cover_url: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    NOTION_DATABASE_ID のDBに1行（=ページ）を作成して page_id を返す
    - title は DB の title property（通常 "名前" / "Name"）に入る想定
    - properties があれば追加でセット（存在しないプロパティはNotion側でエラーになるので注意）
    """
    if not notion_enabled():
        return None

    db_id = _must_env("NOTION_DATABASE_ID")

    props: Dict[str, Any] = {
        "名前": {"title": [{"type": "text", "text": {"content": title}}]},
    }
    # DBのタイトル列が "Name" の場合にも対応したい時は、Notion側を「名前」に統一が一番安全。
    # もし "Name" で運用しているなら、上の "名前" を "Name" に変更してください。

    if properties:
        props.update(properties)

    payload: Dict[str, Any] = {
        "parent": {"type": "database_id", "database_id": db_id},
        "icon": {"type": "emoji", "emoji": icon_emoji},
        "properties": props,
    }

    if cover_url:
        payload["cover"] = {"type": "external", "external": {"url": cover_url}}

    r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


# =============================================================================
# Blocks append helpers
# =============================================================================
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


def append_paragraph(page_id: str, text: str) -> None:
    if not notion_enabled():
        return

    payload = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                },
            }
        ]
    }
    r = requests.patch(f"{API_BASE}/blocks/{page_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()


def append_image(page_id: str, url: str) -> None:
    """
    外部URL画像を1枚だけ追加
    """
    if not notion_enabled():
        return
    if not url:
        return

    payload = {
        "children": [
            {
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": url}},
            }
        ]
    }
    r = requests.patch(f"{API_BASE}/blocks/{page_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()


def append_images(page_id: str, urls: List[str], *, chunk: int = 50) -> None:
    """
    外部URL画像を Notionページに埋め込みで追加（フラットに並べる）
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


def append_toggle_images(page_id: str, title: str, urls: List[str], *, chunk: int = 50) -> None:
    """
    toggle（開閉）ブロックを作り、その子要素に画像を詰める（全文画像用）
    Notion APIは一度に大量のblocksを投げると落ちやすいので chunk 分割。
    """
    if not notion_enabled():
        return

    urls = [u for u in urls if u]
    if not urls:
        return

    # 1) toggleブロックを作成（子は空で作る）
    payload = {
        "children": [
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{"type": "text", "text": {"content": title}}],
                    "children": [],
                },
            }
        ]
    }
    r = requests.patch(f"{API_BASE}/blocks/{page_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()

    toggle_id = r.json()["results"][0]["id"]

    # 2) toggleの子として画像を追加
    for i in range(0, len(urls), chunk):
        part = urls[i:i + chunk]
        children = []
        for u in part:
            children.append(
                {
                    "object": "block",
                    "type": "image",
                    "image": {"type": "external", "external": {"url": u}},
                }
            )
        rr = requests.patch(f"{API_BASE}/blocks/{toggle_id}/children", headers=_headers(), json={"children": children}, timeout=60)
        rr.raise_for_status()
