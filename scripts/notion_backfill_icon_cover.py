# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_backfill_icon_cover.py
#
# 一時的なワンオフ移行スクリプト。
#
# 1. 全部入り天気図/中期予報資料/長期予報資料の既存ページのアイコンを、
#    新しい区分別アイコン(🗾/📅/🌙)に揃える(以前はすべて🗺️で区別不可だった)。
# 2. ギャラリービュー用に、「R2 URL」プロパティに値がある全ページへ、その
#    画像をページカバーとして設定する(過去に作成されたページはカバー未設定
#    のため)。
# =============================================================================

from __future__ import annotations

import os
import time

import requests

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"

TOKEN = os.environ["NOTION_TOKEN"]
DB_ID = os.environ["NOTION_DATABASE_ID"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

PROP_CATEGORY = "区分"
PROP_R2URL = "R2 URL"

ICON_BY_CATEGORY = {
    "全部入り天気図": "🗾",
    "中期予報資料": "📅",
    "長期予報資料": "🌙",
}


def get_current_tags(page: dict):
    ms = page.get("properties", {}).get(PROP_CATEGORY, {}).get("multi_select", [])
    return [x.get("name", "") for x in ms]


def get_current_icon(page: dict) -> str:
    icon = page.get("icon") or {}
    if icon.get("type") == "emoji":
        return icon.get("emoji", "")
    return ""


def get_current_cover(page: dict) -> str:
    cover = page.get("cover") or {}
    if cover.get("type") == "external":
        return cover.get("external", {}).get("url", "")
    return ""


def get_r2_url(page: dict) -> str:
    return page.get("properties", {}).get(PROP_R2URL, {}).get("url") or ""


def iter_all_rows():
    body = {"page_size": 100}
    while True:
        r = requests.post(f"{API_BASE}/databases/{DB_ID}/query", headers=HEADERS, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            yield page
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]


def main():
    checked = 0
    fixed_icon = 0
    fixed_cover = 0
    failed = 0

    for page in iter_all_rows():
        checked += 1
        page_id = page["id"]

        tags = get_current_tags(page)
        expected_icon = None
        for t in tags:
            if t in ICON_BY_CATEGORY:
                expected_icon = ICON_BY_CATEGORY[t]
                break

        current_icon = get_current_icon(page)
        current_cover = get_current_cover(page)
        r2_url = get_r2_url(page)

        payload = {}
        if expected_icon and current_icon != expected_icon:
            payload["icon"] = {"type": "emoji", "emoji": expected_icon}
        if r2_url and not current_cover:
            payload["cover"] = {"type": "external", "external": {"url": r2_url}}

        if not payload:
            continue

        try:
            r = requests.patch(f"{API_BASE}/pages/{page_id}", headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            if "icon" in payload:
                fixed_icon += 1
            if "cover" in payload:
                fixed_cover += 1
        except Exception as e:
            failed += 1
            print(f"[ERR] {page_id}: {e}")

        time.sleep(0.05)

    print(f"[DONE] checked={checked} fixed_icon={fixed_icon} fixed_cover={fixed_cover} failed={failed}")


if __name__ == "__main__":
    main()
