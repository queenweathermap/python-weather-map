# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_strip_title_prefix.py
#
# 一回限りのメンテナンススクリプト。
#
# 「☀️wx 天気図 DB」のタイトルから「{区分}　」の接頭辞を外す(区分は
# バッジで別途表示されるため冗長)。
#   "全部入り天気図　高層天気図・数値予報天気図 結合図"
#       -> "高層天気図・数値予報天気図 結合図"
#   "長期予報資料　1ヶ月予報 結合図" -> "1ヶ月予報 結合図"
#   "中期予報資料　週間予報＋2週間気温予報 結合図" -> "週間予報＋2週間気温予報 結合図"
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import API_BASE, _headers, _must_env

PREFIXES = [
    "全部入り天気図　",
    "長期予報資料　",
    "中期予報資料　",
]


def iter_pages(database_id: str):
    body = {
        "filter": {
            "or": [
                {"property": "タイトル", "title": {"starts_with": p}}
                for p in PREFIXES
            ]
        },
        "page_size": 100,
    }
    while True:
        r = requests.post(
            f"{API_BASE}/databases/{database_id}/query",
            headers=_headers(),
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            title_parts = page["properties"].get("タイトル", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            yield page["id"], title
        if not data.get("has_more"):
            return
        body["start_cursor"] = data["next_cursor"]


def strip_prefix(title: str) -> str:
    for p in PREFIXES:
        if title.startswith(p):
            return title[len(p):]
    return title


def main() -> None:
    database_id = _must_env("NOTION_DATABASE_ID")

    pages = list(iter_pages(database_id))
    print(f"[INFO] {len(pages)} pages to update")

    ok = 0
    failed = []
    for i, (page_id, title) in enumerate(pages, start=1):
        new_title = strip_prefix(title)
        if new_title == title:
            continue
        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=_headers(),
                json={"properties": {"タイトル": {"title": [{"type": "text", "text": {"content": new_title}}]}}},
                timeout=30,
            )
            r.raise_for_status()
            ok += 1
            if i % 50 == 0:
                print(f"[{i}/{len(pages)}] ok={ok} failed={len(failed)}")
        except Exception as e:
            print(f"[NG] {page_id}: {e}")
            failed.append(page_id)

    print(f"\n[DONE] ok={ok} failed={len(failed)} total={len(pages)}")
    if failed:
        print("[FAILED PAGE IDS]")
        for pid in failed:
            print(f"  {pid}")


if __name__ == "__main__":
    main()
