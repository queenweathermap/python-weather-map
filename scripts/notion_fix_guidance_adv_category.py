# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_fix_guidance_adv_category.py
#
# 一時的なワンオフ移行スクリプト。
#
# 資料アーカイブDB(NOTION_DATABASE_ID)で、WCNガイダンス/ADV TGV/ADV気象防災
# アドバイザーガイダンス帳票のページの一部が、過去の区分リネーム作業の際に
# 区分(マルチセレクト)とアイコンが本来と食い違ってしまっている
# (例: タイトルが"Guidance / 20260613 05:44"なのに区分が["ADV"]になっている)。
#
# タイトル文字列から本来のジョブを判定し、区分とアイコンを正しい組み合わせに
# 修正する。
#
#   WCNガイダンス            → 区分=["Guidance"]  icon=🧭
#   ADV 気象防災アドバイザー
#   ガイダンス帳票            → 区分=["ADV"]       icon=📋
#   ADV TGV GIF              → 区分=["ADV"]       icon=🗺️
#
# 区分にPWAタグが付いている場合はそのまま維持する。それ以外の対象外カテゴリ
# (AMeDAS/全部入り天気図/高層観測データ等)のページには一切触れない。
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


def classify(title: str):
    """タイトルから (expected_category, expected_icon) を返す。該当しなければ None。"""
    if not title:
        return None

    if title.startswith("ADV　気象防災アドバイザー ガイダンス帳票") or title.startswith("気象防災アドバイザー ガイダンス帳票"):
        return ("ADV", "📋")

    if title.startswith("ADV　ADV TGV") or title.startswith("ADV TGV"):
        return ("ADV", "🗺️")

    if (
        title.startswith("Guidance　WCNガイダンス")
        or title.startswith("WCNガイダンス")
        or title.startswith("WCN ガイダンス")
        or title.startswith("Guidance / ")
        or title.startswith("ガイダンス / ")
    ):
        return ("Guidance", "🧭")

    return None


def get_title(page: dict) -> str:
    t = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def get_current_tags(page: dict):
    ms = page.get("properties", {}).get(PROP_CATEGORY, {}).get("multi_select", [])
    return [x.get("name", "") for x in ms]


def get_current_icon(page: dict):
    icon = page.get("icon") or {}
    if icon.get("type") == "emoji":
        return icon.get("emoji", "")
    return ""


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
        expected = classify(title)
        if expected is None:
            skipped_no_match += 1
            continue

        expected_category, expected_icon = expected
        current_tags = get_current_tags(page)
        current_icon = get_current_icon(page)

        keep_pwa = "PWA" in current_tags
        new_tags = [expected_category] + (["PWA"] if keep_pwa else [])

        needs_category_fix = current_tags != new_tags
        needs_icon_fix = current_icon != expected_icon

        if not needs_category_fix and not needs_icon_fix:
            continue

        page_id = page["id"]
        payload = {}
        if needs_category_fix:
            payload["properties"] = {
                PROP_CATEGORY: {"multi_select": [{"name": t} for t in new_tags]}
            }
        if needs_icon_fix:
            payload["icon"] = {"type": "emoji", "emoji": expected_icon}

        try:
            r = requests.patch(f"{API_BASE}/pages/{page_id}", headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            fixed += 1
            print(f"[FIX] {page_id} title={title!r} tags {current_tags}->{new_tags} icon {current_icon!r}->{expected_icon!r}")
        except Exception as e:
            failed += 1
            print(f"[ERR] {page_id} title={title!r}: {e}")

        time.sleep(0.05)

    print(f"[DONE] checked={checked} fixed={fixed} failed={failed} skipped_no_match={skipped_no_match}")


if __name__ == "__main__":
    main()
