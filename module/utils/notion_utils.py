# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_utils.py
#
# Notion API ユーティリティ
# - DBへ1行（=ページ）を作る: create_db_row()
# - ページ配下にブロック追加:
#     append_heading(), append_toggle(), append_images(),
#     append_text(), append_code_block(), append_files(), append_bookmark()
# - 代表画像をカバーにする: set_page_cover()
#
# 必要な環境変数
#   NOTION_TOKEN
#
# DB運用（本命）
#   NOTION_DATABASE_ID
#
# 任意（機能ON/OFF）
#   NOTION_ENABLE=1         # 0なら何もしない（テスト用）
#
# 任意（DBプロパティ名が環境で違う場合の上書き）
#   NOTION_PROP_TITLE="名前"
#   NOTION_PROP_CATEGORY="区分"
#   NOTION_PROP_INIT_JST="初期時刻（JST）"
#   NOTION_PROP_MEMO="メモ"
#   NOTION_PROP_R2URL="R2 URL"
#   NOTION_PROP_AUTOGEN="自動生成"
#   NOTION_PROP_RJTD="RJTD"
#   NOTION_PROP_PREFIX="prefix"
# =============================================================================

from __future__ import annotations

import os
from typing import List, Optional, Dict, Any

import requests


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


# -----------------------------------------------------------------------------
# DB property names (overrideable)
# -----------------------------------------------------------------------------
def _prop_title() -> str:
    return _env("NOTION_PROP_TITLE", "名前")


def _prop_category() -> str:
    return _env("NOTION_PROP_CATEGORY", "区分")


def _prop_init_jst() -> str:
    return _env("NOTION_PROP_INIT_JST", "初期時刻（JST）")


def _prop_memo() -> str:
    return _env("NOTION_PROP_MEMO", "メモ")


def _prop_r2url() -> str:
    return _env("NOTION_PROP_R2URL", "R2 URL")


def _prop_autogen() -> str:
    return _env("NOTION_PROP_AUTOGEN", "自動生成")


def _prop_rjtd() -> str:
    return _env("NOTION_PROP_RJTD", "RJTD")


def _prop_prefix() -> str:
    return _env("NOTION_PROP_PREFIX", "prefix")


# -----------------------------------------------------------------------------
# DB row create
# -----------------------------------------------------------------------------
def create_db_row(
    *,
    title: str,
    category: str,                 # "ADV" or "Weathercaster"
    init_jst_iso: str,             # ISO8601 with timezone, e.g. "2026-02-03T09:00:00+09:00"
    memo: str = "",
    rjtd: str = "",
    prefix: str = "",
    r2_url: str = "",
    autogen: bool = True,
    icon_emoji: str = "🗺️",
) -> Optional[str]:
    """
    指定DBへ1行（=ページ）を作成して page_id を返す。
    """
    if not notion_enabled():
        return None

    db_id = _must_env("NOTION_DATABASE_ID")

    props: Dict[str, Any] = {
        _prop_title(): {"title": [{"type": "text", "text": {"content": title}}]},
        _prop_category(): {"select": {"name": category}},
        _prop_init_jst(): {"date": {"start": init_jst_iso}},
    }

    if memo:
        props[_prop_memo()] = {"rich_text": [{"type": "text", "text": {"content": memo}}]}

    if rjtd:
        props[_prop_rjtd()] = {"rich_text": [{"type": "text", "text": {"content": rjtd}}]}
    if prefix:
        props[_prop_prefix()] = {"rich_text": [{"type": "text", "text": {"content": prefix}}]}

    if r2_url:
        props[_prop_r2url()] = {"url": r2_url}
    if autogen is not None:
        props[_prop_autogen()] = {"checkbox": bool(autogen)}

    payload = {
        "parent": {"type": "database_id", "database_id": db_id},
        "icon": {"type": "emoji", "emoji": icon_emoji},
        "properties": props,
    }

    r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def set_page_cover(page_id: str, image_url: str) -> None:
    """
    ページのカバー画像を外部URLで設定（代表画像用）
    """
    if not notion_enabled():
        return
    if not image_url:
        return

    payload = {"cover": {"type": "external", "external": {"url": image_url}}}
    r = requests.patch(f"{API_BASE}/pages/{page_id}", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()


# -----------------------------------------------------------------------------
# Blocks append
# -----------------------------------------------------------------------------
def append_heading(page_or_block_id: str, text: str, *, level: int = 2) -> Optional[str]:
    """
    見出しブロック（heading_2 / heading_3）を追加し、その block_id を返す
    """
    if not notion_enabled():
        return None

    if level not in (2, 3):
        level = 2
    t = "heading_2" if level == 2 else "heading_3"

    payload = {
        "children": [
            {
                "object": "block",
                "type": t,
                t: {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }
        ]
    }

    r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()

    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]["id"]



def append_toggle(page_or_block_id: str, title: str) -> Optional[str]:
    """
    toggleブロックを追加し、その block_id を返す
    """
    if not notion_enabled():
        return None
    if not title:
        return None

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
    r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()

    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]["id"]


def append_images(page_or_block_id: str, urls: List[str], *, chunk: int = 50) -> None:
    """
    外部URL画像を Notion に埋め込みで追加（ページでもトグルでもOK）
    """
    if not notion_enabled():
        return

    urls = [u for u in (urls or []) if u]
    if not urls:
        return

    for i in range(0, len(urls), chunk):
        part = urls[i:i + chunk]
        children = [
            {
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": u}},
            }
            for u in part
        ]

        payload = {"children": children}
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_text(page_or_block_id: str, text: str, *, chunk_chars: int = 1800) -> None:
    """
    段落（paragraph）ブロックとしてテキストを追加
    """
    if not notion_enabled():
        return

    text = (text or "").strip()
    if not text:
        return

    for i in range(0, len(text), chunk_chars):
        part = text[i:i + chunk_chars]
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": part}}]},
                }
            ]
        }
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_code_block(page_or_block_id: str, text: str, *, language: str = "plain text", chunk_chars: int = 1800) -> None:
    """
    codeブロックとして追加（表の貼り付けやログ用途）
    """
    if not notion_enabled():
        return

    text = (text or "").rstrip()
    if not text:
        return

    # code も長いと落ちるので分割
    for i in range(0, len(text), chunk_chars):
        part = text[i:i + chunk_chars]
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": part}}],
                        "language": language,
                    },
                }
            ]
        }
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_files(page_or_block_id: str, files: List[dict], *, chunk: int = 20) -> None:
    """
    外部URLファイルを Notion に添付（fileブロック）
    files: [{"url": "...", "name": "xxx.csv"}, ...]
    """
    if not notion_enabled():
        return

    files = [f for f in (files or []) if f.get("url")]
    if not files:
        return

    for i in range(0, len(files), chunk):
        part = files[i:i + chunk]
        children = []
        for f in part:
            url = (f.get("url") or "").strip()
            name = (f.get("name") or "").strip()

            file_obj = {
                "object": "block",
                "type": "file",
                "file": {"type": "external", "external": {"url": url}},
            }
            if name:
                file_obj["file"]["caption"] = [{"type": "text", "text": {"content": name}}]

            children.append(file_obj)

        payload = {"children": children}
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_bookmark(page_or_block_id: str, url: str, *, caption: str = "") -> None:
    """
    ブックマーク（リンクカード）を追加
    """
    if not notion_enabled():
        return

    url = (url or "").strip()
    if not url:
        return

    block: Dict[str, Any] = {
        "object": "block",
        "type": "bookmark",
        "bookmark": {"url": url},
    }

    if caption:
        block["bookmark"]["caption"] = [{"type": "text", "text": {"content": caption}}]

    payload = {"children": [block]}
    r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
