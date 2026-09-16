# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_unify_jma_category.py
#
# 一回限りのメンテナンススクリプト。
#
# 「☀️wx 天気図 DB」の区分プロパティが厳密に ["JMA"] だけになっている行を、
# 全部 ["全部入り天気図"] に統一する（PWAタグは追加しない）。
#
# Notion REST APIを直接叩いて、data_sources/{id}/query をカーソルで
# 完全にページングする（MCP経由のSQLモードは1呼び出しあたり実質100件までしか
# 返らない制限があり、検索ベースの手段は50件キャップかつページングが無いため、
# どちらも大量件数の完全な列挙には向かない）。
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import API_BASE, _headers, _must_env


def resolve_data_source_id(database_id: str) -> str:
    r = requests.get(f"{API_BASE}/databases/{database_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    data_sources = r.json().get("data_sources") or []
    if not data_sources:
        raise RuntimeError(f"database {database_id} has no data_sources")
    return data_sources[0]["id"]


def iter_jma_only_pages(data_source_id: str):
    """区分が厳密に ["JMA"] だけの行を、カーソルで全件たどって返す。"""
    body = {
        "filter": {"property": "区分", "multi_select": {"contains": "JMA"}},
        "page_size": 100,
    }
    while True:
        r = requests.post(
            f"{API_BASE}/data_sources/{data_source_id}/query",
            headers=_headers(),
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            tags = [t["name"] for t in page["properties"].get("区分", {}).get("multi_select", [])]
            if tags == ["JMA"]:
                yield page["id"]
        if not data.get("has_more"):
            return
        body["start_cursor"] = data["next_cursor"]


def main() -> None:
    database_id = _must_env("NOTION_DATABASE_ID")
    data_source_id = resolve_data_source_id(database_id)

    page_ids = list(iter_jma_only_pages(data_source_id))
    print(f"[INFO] {len(page_ids)} pages with 区分=['JMA'] found")

    ok = 0
    failed = []
    for i, page_id in enumerate(page_ids, start=1):
        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=_headers(),
                json={"properties": {"区分": {"multi_select": [{"name": "全部入り天気図"}]}}},
                timeout=30,
            )
            r.raise_for_status()
            ok += 1
            if i % 50 == 0:
                print(f"[{i}/{len(page_ids)}] ok={ok} failed={len(failed)}")
        except Exception as e:
            print(f"[NG] {page_id}: {e}")
            failed.append(page_id)

    print(f"\n[DONE] ok={ok} failed={len(failed)} total={len(page_ids)}")
    if failed:
        print("[FAILED PAGE IDS]")
        for pid in failed:
            print(f"  {pid}")


if __name__ == "__main__":
    main()
