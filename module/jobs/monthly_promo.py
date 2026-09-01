# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/monthly_promo.py
#
# 毎月10日、その月の1日 00Zサイクルの「全部入り天気図」(07_DASHBOARD_JMA_DIRECT)を
# 1枚、177chart.comへの誘導文言つきでBluesky・Threads・Facebook・Instagramに投稿する。
#
#   画像は新たに生成しない。07_DASHBOARD_JMA_DIRECTは00Z/12Zサイクルごとに
#   R2へアップロードされ、同時にPWA配信履歴(Notion)へ
#   「発行時刻表示」(例: "2026/09/01 00Z (09:00JST)")付きで記録されている
#   （module/utils/recent_items.py / weather_map.py notify_dm_subscribers）。
#   このDBを「1日 00Z」で検索してR2公開URLを取得し、そこから画像バイトを
#   ダウンロードして各SNSへ投稿する（Blueskyはバイナリのblobアップロードが必須なため）。
#   R2保存期間は30日のため、10日時点でも問題なく残っている。
# =============================================================================

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from module.jobs.climate_3yr import upload_r2
from module.utils.sns_utils import post_bluesky, post_threads, post_facebook, post_instagram

NOTION_VERSION = "2025-09-03"
API_BASE = "https://api.notion.com/v1"
TZ = ZoneInfo("Asia/Tokyo")

SITE_URL = "https://177chart.com/"
DASHBOARD_CATEGORY = "全部入り天気図"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {_env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _resolve_data_source_id(db_id: str) -> str:
    r = requests.get(f"{API_BASE}/databases/{db_id}", headers=_notion_headers(), timeout=30)
    r.raise_for_status()
    data_sources = r.json().get("data_sources", [])
    if not data_sources:
        raise RuntimeError(f"database {db_id} has no data_sources")
    return data_sources[0]["id"]


def find_dashboard_image_url(year: int, month: int) -> str:
    """その月の1日 00Zサイクルの「全部入り天気図」のR2公開URLをPWA配信履歴から探す。"""
    db_id = _env("NOTION_PWA_HISTORY_DATABASE_ID")
    if not db_id:
        print("[ERR] NOTION_PWA_HISTORY_DATABASE_ID 未設定")
        return ""

    try:
        data_source_id = _resolve_data_source_id(db_id)
    except requests.RequestException as e:
        print(f"[ERR] Notion データソース取得失敗: {e}")
        return ""

    prefix = f"{year}/{month:02d}/01 00Z"
    body = {
        "filter": {
            "and": [
                {"property": "カテゴリ", "select": {"equals": DASHBOARD_CATEGORY}},
                {"property": "発行時刻表示", "rich_text": {"starts_with": prefix}},
            ]
        },
        "page_size": 5,
    }
    try:
        r = requests.post(
            f"{API_BASE}/data_sources/{data_source_id}/query",
            headers=_notion_headers(), json=body, timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERR] Notion 検索失敗: {e}")
        return ""

    results = r.json().get("results", [])
    if not results:
        print(f"[WARN] 該当する全部入り天気図が見つかりません（{prefix}）")
        return ""

    url = results[0].get("properties", {}).get("URL", {}).get("url", "") or ""
    if url:
        print(f"[OK] 対象画像: {prefix} → {url}")
    return url


def main() -> None:
    print("=== Start Monthly Promo (全部入り天気図) ===")
    now = datetime.now(TZ)
    year, month = now.year, now.month

    image_url = find_dashboard_image_url(year, month)
    if not image_url:
        print("=== Skip (image not found) ===")
        return

    try:
        r = requests.get(image_url, timeout=60)
        r.raise_for_status()
        png = r.content
    except Exception as e:
        print(f"[ERR] 画像ダウンロード失敗: {e}")
        return

    caption = (
        f"🗾 {month}月1日 00Z 全部入り天気図\n"
        f"高層天気図・数値予報天気図をまとめて1枚にした「全部入り天気図」です。\n"
        f"毎日の最新版はこちらから → {SITE_URL}\n"
        f"#気象 #天気図 #177chart"
    )
    alt = f"全部入り天気図 {month}月1日 00Z"
    images = [(png, alt)]

    post_bluesky(text=caption, images=images)
    post_threads(text=caption, images=images, r2_upload=upload_r2)
    post_facebook(text=caption, images=images)
    post_instagram(text=caption, images=images, r2_upload=upload_r2)

    print("=== Done ===")


if __name__ == "__main__":
    main()
