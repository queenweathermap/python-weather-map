# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_backfill_haishin_datetime.py
#
# 一時的なワンオフ移行スクリプト。
# 資料アーカイブDB(NOTION_DATABASE_ID)で「配信日時」プロパティが未入力の
# ページ(古いタイトル形式で作られたもの)を対象に、タイトル文字列から
# 日時を抽出して「配信日時」に書き込む。
#
# 想定タイトル形式:
#   "Weathercaster / 20260204 09:00 JST"
#   "JMA / 20260825 21:00 JST"
#   "ADV TGV / 20260204 09:00 JST"
#   "ADV TGV GIF / 20260914 15:00 JST"
#   "ガイダンス / 2026/06/15 05:00 JST"
#   "Guidance / 20260613 05:44"
#   "AMeDAS 秋田 / 09/15 17:05"   (年が無いので createdTime から推定)
#
# 完了後は関連ファイル(このスクリプトとワークフロー)を削除する。
# =============================================================================

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"
JST = ZoneInfo("Asia/Tokyo")

TOKEN = os.environ["NOTION_TOKEN"]
DB_ID = os.environ["NOTION_DATABASE_ID"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

PROP_TITLE = "タイトル"
PROP_INIT_JST = "配信日時"

PAT_Y_M_D_HM = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})[^\d]{1,5}(\d{1,2}):(\d{2})")
PAT_YMD_HM = re.compile(r"(\d{4})(\d{2})(\d{2})[^\d]{1,5}(\d{1,2}):(\d{2})")
PAT_MD_HM = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})[^\d]{1,5}(\d{1,2}):(\d{2})")


def parse_title_datetime(title: str, created_iso: str):
    if not title:
        return None

    m = PAT_Y_M_D_HM.search(title)
    if m:
        y, mo, d, hh, mm = map(int, m.groups())
        return datetime(y, mo, d, hh, mm, tzinfo=JST)

    m = PAT_YMD_HM.search(title)
    if m:
        y, mo, d, hh, mm = map(int, m.groups())
        return datetime(y, mo, d, hh, mm, tzinfo=JST)

    m = PAT_MD_HM.search(title)
    if m:
        mo, d, hh, mm = map(int, m.groups())
        created_dt = datetime.fromisoformat(created_iso.replace("Z", "+00:00")).astimezone(JST)
        year = created_dt.year
        if mo == 12 and created_dt.month == 1:
            year -= 1
        elif mo == 1 and created_dt.month == 12:
            year += 1
        return datetime(year, mo, d, hh, mm, tzinfo=JST)

    return None


def get_title(page: dict) -> str:
    t = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def query_empty_rows():
    rows = []
    body = {
        "filter": {"property": PROP_INIT_JST, "date": {"is_empty": True}},
        "page_size": 100,
    }
    while True:
        r = requests.post(f"{API_BASE}/databases/{DB_ID}/query", headers=HEADERS, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        rows.extend(data["results"])
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]
    return rows


def main():
    rows = query_empty_rows()
    print(f"[INFO] {len(rows)} pages with empty {PROP_INIT_JST}")

    ok = 0
    failed = 0
    unmatched = []

    for page in rows:
        page_id = page["id"]
        title = get_title(page)
        created_iso = page["created_time"]
        dt = parse_title_datetime(title, created_iso)

        if dt is None:
            unmatched.append((page_id, title, created_iso))
            failed += 1
            continue

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=HEADERS,
                json={"properties": {PROP_INIT_JST: {"date": {"start": dt.isoformat()}}}},
                timeout=30,
            )
            r.raise_for_status()
            ok += 1
        except Exception as e:
            print(f"[ERR] {page_id} title={title!r}: {e}")
            failed += 1

        time.sleep(0.05)

    print(f"[DONE] ok={ok} failed={failed} total={len(rows)}")

    if unmatched:
        print(f"[UNMATCHED] {len(unmatched)} rows could not be parsed:")
        for pid, t, c in unmatched[:80]:
            print(f"  {pid} created={c} title={t!r}")


if __name__ == "__main__":
    main()
