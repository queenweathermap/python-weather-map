# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_revert_bad_haishin_fix.py
#
# 一時的なワンオフ移行スクリプト。
#
# notion_fix_haishin_actual_time.py は「配信日時」を各ページのcreated_time
# に書き戻す想定だったが、対象ページの多くが以前の区分リネーム作業(schema
# RENAME COLUMN)で作成時刻がリセットされていたため、意図せず同じ誤った時刻
# に揃ってしまった。途中でキャンセルしたが、実行された分の「配信日時」を
# 元(ラベル時刻)に近い値へ戻す。
#
#   ADV TGV        → タイトル中のYYYYMMDD HH:MMをそのまま使う(正確に復元可能)
#   エマグラム      → ヘッダの日付 + 21:00 JST(旧コードの前日21時ラベル)
#   ウィンドプロファイラ → ヘッダの日付 + 03:00 JST(cronの本来の狙い時刻を近似値として使用)
#
# 対象は「キャンセルされたスクリプトの実行時間帯にlast_edited_timeが入って
# いるページ」のみ。今日未明分として手動で正しい実投稿時刻に修正済みの
# 2ページはexplicitに除外する。
# =============================================================================

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
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
PROP_CATEGORY = "区分"
PROP_HEADER = "ヘッダ"
PROP_INIT_JST = "配信日時"

# キャンセルされたnotion_fix_haishin_actual_time.py実行の実際の稼働ウィンドウ
# (GitHub Actionsログで確認: 開始04:56:24.324Z、キャンセル04:57:43.301Z)。
# 前後に数秒のバッファを設ける。他の(無関係な)一括修正作業による直近の
# last_edited_timeと混同しないよう、ゆるい「直近N分」ではなくこの正確な
# 時間帯を使う。
TOUCHED_WINDOW_START = datetime(2026, 9, 18, 4, 56, 20, tzinfo=timezone.utc)
TOUCHED_WINDOW_END = datetime(2026, 9, 18, 4, 57, 50, tzinfo=timezone.utc)

EXCLUDE_PAGE_IDS = {
    "3de8253e-4a19-81e3-8e96-ee16752cb09c",  # emagram (今日未明、実投稿時刻で修正済み)
    "3de8253e-4a19-81ed-b122-e7aaefe631ba",  # windprofiler (今日未明、実投稿時刻で修正済み)
}

PAT_YMD_HM = re.compile(r"(\d{4})(\d{2})(\d{2})[^\d]{1,5}(\d{1,2}):(\d{2})")
PAT_HEADER_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")


def get_title(page: dict) -> str:
    t = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def get_header(page: dict) -> str:
    rt = page.get("properties", {}).get(PROP_HEADER, {}).get("rich_text", [])
    return "".join(x.get("plain_text", "") for x in rt)


def get_tags(page: dict):
    ms = page.get("properties", {}).get(PROP_CATEGORY, {}).get("multi_select", [])
    return [x.get("name", "") for x in ms]


def revert_value(title: str, header: str):
    """(True, iso_string) を返す。判定できない場合は (False, "")。"""
    if "ADV TGV" in title:
        m = PAT_YMD_HM.search(title)
        if not m:
            return False, ""
        y, mo, d, hh, mm = map(int, m.groups())
        return True, datetime(y, mo, d, hh, mm, tzinfo=JST).isoformat()

    if title.startswith("エマグラム"):
        m = PAT_HEADER_DATE.search(header)
        if not m:
            return False, ""
        y, mo, d = map(int, m.groups())
        return True, datetime(y, mo, d, 21, 0, tzinfo=JST).isoformat()

    if title.startswith("ウィンドプロファイラ"):
        m = PAT_HEADER_DATE.search(header)
        if not m:
            return False, ""
        y, mo, d = map(int, m.groups())
        return True, datetime(y, mo, d, 3, 0, tzinfo=JST).isoformat()

    return False, ""


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
    touched_candidates = 0
    reverted = 0
    failed = 0
    unresolvable = []

    for page in iter_all_rows():
        checked += 1
        page_id = page["id"]
        if page_id in EXCLUDE_PAGE_IDS:
            continue

        title = get_title(page)
        tags = get_tags(page)
        if not is_target(title, tags):
            continue

        last_edited = datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00"))
        if not (TOUCHED_WINDOW_START <= last_edited <= TOUCHED_WINDOW_END):
            continue  # 今回の事故の時間帯に触れられていない(対象外)

        touched_candidates += 1
        header = get_header(page)
        ok, iso_value = revert_value(title, header)
        if not ok:
            unresolvable.append((page_id, title, header))
            continue

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=HEADERS,
                json={"properties": {PROP_INIT_JST: {"date": {"start": iso_value}}}},
                timeout=30,
            )
            r.raise_for_status()
            reverted += 1
            print(f"[REVERT] {page_id} title={title!r} -> {iso_value}")
        except Exception as e:
            failed += 1
            print(f"[ERR] {page_id} title={title!r}: {e}")

        time.sleep(0.05)

    print(
        f"[DONE] checked={checked} touched_candidates={touched_candidates} "
        f"reverted={reverted} failed={failed} unresolvable={len(unresolvable)}"
    )
    for pid, t, h in unresolvable[:50]:
        print(f"  [UNRESOLVED] {pid} title={t!r} header={h!r}")


if __name__ == "__main__":
    main()
