# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_fix_haishin_actual_time.py
#
# 一時的なワンオフ移行スクリプト。
#
# エマグラム/ウィンドプロファイラ/ADV TGV GIFの3ジョブは、2026-09-18の修正
# (コミット56abf3b)より前は「配信日時」に観測・初期値のラベル時刻(前日21時
# JST等)を入れてしまっており、実際の投稿時刻とズレていた。
# 該当する既存ページについて、Notion自身のページ作成時刻(created_time、
# ページ作成=画像アップロード直後でほぼ実際の投稿時刻と一致)を「配信日時」
# に書き戻して補正する。
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

PROP_TITLE = "タイトル"
PROP_CATEGORY = "区分"
PROP_INIT_JST = "配信日時"


def get_title(page: dict) -> str:
    t = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def get_tags(page: dict):
    ms = page.get("properties", {}).get(PROP_CATEGORY, {}).get("multi_select", [])
    return [x.get("name", "") for x in ms]


def is_target(title: str, tags) -> bool:
    if title.startswith("エマグラム") and "高層観測データ" in tags:
        return True
    if title.startswith("ウィンドプロファイラ") and "高層観測データ" in tags:
        return True
    if ("ADV TGV" in title) and "ADV" in tags and not title.startswith("ADV　気象防災アドバイザー"):
        return True
    return False


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
    fixed = 0
    failed = 0
    skipped_no_match = 0

    for page in iter_all_rows():
        checked += 1
        title = get_title(page)
        tags = get_tags(page)

        if not is_target(title, tags):
            skipped_no_match += 1
            continue

        page_id = page["id"]
        created_time = page["created_time"]

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=HEADERS,
                json={"properties": {PROP_INIT_JST: {"date": {"start": created_time}}}},
                timeout=30,
            )
            r.raise_for_status()
            fixed += 1
        except Exception as e:
            failed += 1
            print(f"[ERR] {page_id} title={title!r}: {e}")

        time.sleep(0.05)

    print(f"[DONE] checked={checked} fixed={fixed} failed={failed} skipped_no_match={skipped_no_match}")


if __name__ == "__main__":
    main()
