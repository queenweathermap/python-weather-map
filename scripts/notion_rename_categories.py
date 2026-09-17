# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_rename_categories.py
#
# 一回限りのメンテナンススクリプト。
#
# 「☀️wx 天気図 DB」の区分(マルチセレクト)を以下のようにリネーム/統合する。
# 他に付いているタグ(PWAなど)は保持したまま、対象タグだけ置き換える。
#   Amedas          -> AMeDAS
#   エマグラム       -> 高層観測
#   ウィンドプロファイラ -> 高層観測
#   WCNガイダンス     -> Guidance
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import API_BASE, _headers, _must_env

RENAME_MAP = {
    "Amedas": "AMeDAS",
    "エマグラム": "高層観測",
    "ウィンドプロファイラ": "高層観測",
    "WCNガイダンス": "Guidance",
}


def iter_matching_pages(database_id: str):
    body = {
        "filter": {
            "or": [
                {"property": "区分", "multi_select": {"contains": name}}
                for name in RENAME_MAP
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
            tags = [t["name"] for t in page["properties"].get("区分", {}).get("multi_select", [])]
            if any(t in RENAME_MAP for t in tags):
                yield page["id"], tags
        if not data.get("has_more"):
            return
        body["start_cursor"] = data["next_cursor"]


def main() -> None:
    database_id = _must_env("NOTION_DATABASE_ID")

    pages = list(iter_matching_pages(database_id))
    print(f"[INFO] {len(pages)} pages to update")

    ok = 0
    failed = []
    for i, (page_id, tags) in enumerate(pages, start=1):
        new_tags = []
        seen = set()
        for t in tags:
            nt = RENAME_MAP.get(t, t)
            if nt not in seen:
                new_tags.append(nt)
                seen.add(nt)

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=_headers(),
                json={"properties": {"区分": {"multi_select": [{"name": t} for t in new_tags]}}},
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
