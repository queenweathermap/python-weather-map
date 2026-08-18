# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/recent_items.py
#
# PWA（177chart.com会員ページ）の「最近の配信」一覧表示用。
# 配信のたびに、購読者DBとは別の「PWA配信履歴」Notionデータベースへ1行記録する。
# Worker側（weather-dm-signup）の GET /recent がこのDBを読み出して一覧表示する。
#
# 必要な環境変数
#   NOTION_TOKEN                     （module/utils/notion_subscribers.py と共有）
#   NOTION_PWA_HISTORY_DATABASE_ID
# =============================================================================

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import requests

NOTION_VERSION = "2025-09-03"
API_BASE = "https://api.notion.com/v1"


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


def record_recent_item(title: str, url: str, category: str) -> None:
    """PWA配信履歴に1行追加する。失敗しても配信自体は止めたくないので例外は握りつぶす。"""
    db_id = _env("NOTION_PWA_HISTORY_DATABASE_ID")
    if not db_id:
        print("[INFO] NOTION_PWA_HISTORY_DATABASE_ID未設定のためPWA配信履歴の記録をスキップ")
        return

    body = {
        "parent": {"database_id": db_id},
        "properties": {
            "タイトル": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "カテゴリ": {"select": {"name": category}},
            "配信日時": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        },
    }

    try:
        r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=body, timeout=30)
        if not r.ok:
            print(f"[WARN] PWA配信履歴の記録失敗 status={r.status_code} body={r.text[:300]}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"[WARN] PWA配信履歴の記録中に例外: {exc}", file=sys.stderr)
