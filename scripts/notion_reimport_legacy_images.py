# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_reimport_legacy_images.py
#
# 一回限りのメンテナンススクリプト。
#
# 「高層天気図・数値予報天気図 結合図」「週間予報＋2週間気温予報 結合図」
# 「1ヶ月予報 結合図」という旧タイトル形式で作られたNotionページのうち、
# 画像インポートに失敗して本文が空だった76件を、MCP経由でR2の外部リンクと
# して一時的に貼り直した(scripts/legacy_notion_repair_list.json)。
# このスクリプトは、その外部リンクをNotion管理ストレージへの正規インポート
# (file_upload / external_url)に置き換える。
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import (
    API_BASE,
    _headers,
    append_imported_images_from_urls,
)

DATA_FILE = REPO_ROOT / "scripts" / "legacy_notion_repair_list.json"


def _delete_existing_children(page_id: str) -> None:
    """MCP経由で貼った外部リンク画像(や既存ブロック)を消してから作り直す。"""
    r = requests.get(
        f"{API_BASE}/blocks/{page_id}/children",
        headers=_headers(),
        params={"page_size": 100},
        timeout=60,
    )
    r.raise_for_status()
    for block in r.json().get("results", []):
        block_id = block["id"]
        dr = requests.delete(f"{API_BASE}/blocks/{block_id}", headers=_headers(), timeout=60)
        if dr.status_code >= 300:
            print(f"  [WARN] failed to delete old block {block_id}: {dr.status_code} {dr.text[:200]}")


def main() -> None:
    entries = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    print(f"[INFO] {len(entries)} pages to reimport")

    ok = 0
    failed = []

    for i, entry in enumerate(entries, start=1):
        page_id = entry["page_id"]
        r2_url = entry["r2_url"]
        filename = r2_url.rsplit("/", 1)[-1]

        print(f"[{i}/{len(entries)}] {page_id} <- {r2_url}")
        try:
            _delete_existing_children(page_id)
            append_imported_images_from_urls(
                page_id,
                [(filename, r2_url, "image/png")],
                chunk=1,
                timeout_seconds=180,
                poll_seconds=2.0,
            )
            print("  [OK] reimported")
            ok += 1
        except Exception as e:
            print(f"  [NG] {e}")
            failed.append({"page_id": page_id, "r2_url": r2_url, "error": str(e)})

    print(f"\n[DONE] ok={ok} failed={len(failed)} total={len(entries)}")
    if failed:
        print("[FAILED ENTRIES]")
        for f in failed:
            print(f"  {f['page_id']}  {f['r2_url']}  -> {f['error']}")


if __name__ == "__main__":
    main()
