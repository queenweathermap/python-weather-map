# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_fix_koso_category.py
#
# 一回限りのメンテナンススクリプト。
#
# 区分「高層観測」を「高層観測データ」にリネームし、タイトルから
# 「高層観測データ　」の接頭辞を外す(区分側に持たせたため冗長になった)。
#   タイトル: "高層観測データ　エマグラム　前日まとめ（15地点）"
#           -> "エマグラム　前日まとめ（15地点）"
#   区分:    "高層観測" -> "高層観測データ"
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import API_BASE, _headers, _must_env

OLD_TAG = "高層観測"
NEW_TAG = "高層観測データ"
TITLE_PREFIX = "高層観測データ　"


def iter_matching_pages(database_id: str):
    body = {
        "filter": {"property": "区分", "multi_select": {"contains": OLD_TAG}},
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
            props = page["properties"]
            tags = [t["name"] for t in props.get("区分", {}).get("multi_select", [])]
            title_parts = props.get("タイトル", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            if OLD_TAG in tags:
                yield page["id"], tags, title
        if not data.get("has_more"):
            return
        body["start_cursor"] = data["next_cursor"]


def main() -> None:
    database_id = _must_env("NOTION_DATABASE_ID")

    pages = list(iter_matching_pages(database_id))
    print(f"[INFO] {len(pages)} pages to update")

    ok = 0
    failed = []
    for i, (page_id, tags, title) in enumerate(pages, start=1):
        new_tags = [NEW_TAG if t == OLD_TAG else t for t in tags]
        new_title = title[len(TITLE_PREFIX):] if title.startswith(TITLE_PREFIX) else title

        props = {
            "区分": {"multi_select": [{"name": t} for t in new_tags]},
        }
        if new_title != title:
            props["タイトル"] = {"title": [{"type": "text", "text": {"content": new_title}}]}

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=_headers(),
                json={"properties": props},
                timeout=30,
            )
            r.raise_for_status()
            ok += 1
            if i % 20 == 0:
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
