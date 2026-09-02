# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/recent_items.py
#
# PWA（177chart.com会員ページ）の「最近の配信」一覧表示用。
# 配信のたびに、購読者DBとは別の「PWA配信履歴」Notionデータベースへ1行記録する。
# Worker側（weather-dm-signup）の GET /recent がこのDBを読み出して一覧表示する。
#
# 必要な環境変数
#   NOTION_TOKEN                     （module/utils/notion_subscribers.py と共有）
#   NOTION_PWA_HISTORY_DATABASE_ID
# =============================================================================

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

NOTION_VERSION = "2025-09-03"
API_BASE = "https://api.notion.com/v1"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_must_env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def record_recent_item(
    title: str,
    url: str,
    category: str,
    issue_time_label: str = "",
    *,
    size_bytes: int = 0,
) -> None:
    """PWA配信履歴に1行追加する。失敗しても配信自体は止めたくないので例外は握りつぶす。

    issue_time_label: Discordの投稿文と同じ「発行基準時刻」の表示文字列
    （例: "2026-08-18 09:00 JST" や "2026-08-18 00Z"）。ギャラリー表示用で、
    配信日時（このNotion行が作られた時刻・30日保存期限の判定に使う）とは別物。

    size_bytes: 画像のファイルサイズ。会員ページ側がタップした瞬間に（何も
    フェッチせず同期的に）「iOSで共有シート経由の自動ダウンロードにするか、
    大きいので別タブで開くだけにするか」を判断するために使う。iOSの
    navigator.share()はユーザー操作から間を置かずに呼ばないと失敗するため、
    非同期のサイズ確認（HEADリクエスト等）に頼らずタップ時点で即判定できる
    必要がある。
    """
    db_id = _env("NOTION_PWA_HISTORY_DATABASE_ID")
    if not db_id:
        print("[INFO] NOTION_PWA_HISTORY_DATABASE_ID未設定のためPWA配信履歴の記録をスキップ")
        return

    body = {
        "parent": {"database_id": db_id},
        "properties": {
            "タイトル": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "カテゴリ": {"select": {"name": category}},
            "配信日時": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
            "発行時刻表示": {"rich_text": [{"text": {"content": issue_time_label}}]},
            "サイズ": {"number": size_bytes},
        },
    }

    try:
        r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=body, timeout=30)
        if not r.ok:
            print(f"[WARN] PWA配信履歴の記録失敗 status={r.status_code} body={r.text[:300]}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"[WARN] PWA配信履歴の記録中に例外: {exc}", file=sys.stderr)


def _resolve_data_source_id(db_id: str) -> str:
    r = requests.get(f"{API_BASE}/databases/{db_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    data_sources = r.json().get("data_sources", [])
    if not data_sources:
        raise RuntimeError(f"NOTION_PWA_HISTORY_DATABASE_ID={db_id} has no data_sources")
    return data_sources[0]["id"]


def cleanup_old_recent_items(retention_days: int = 21) -> None:
    """R2オブジェクトの保存期間（既定21日）に合わせて、それより古いPWA配信履歴を削除する。
    これをしないと、R2側で画像が消えた後もギャラリーにリンク切れの項目が残ってしまう。
    NOTION_PWA_HISTORY_DATABASE_ID未設定の場合（このDBを使わないワークフロー）は何もしない。"""
    db_id = _env("NOTION_PWA_HISTORY_DATABASE_ID")
    if not db_id:
        return

    try:
        data_source_id = _resolve_data_source_id(db_id)
    except requests.RequestException as exc:
        print(f"[WARN] PWA配信履歴のクリーンアップ中に例外: {exc}", file=sys.stderr)
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    deleted = 0
    cursor = None

    while True:
        body = {
            "filter": {"property": "配信日時", "date": {"before": cutoff}},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor

        try:
            r = requests.post(
                f"{API_BASE}/data_sources/{data_source_id}/query",
                headers=_headers(),
                json=body,
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f"[WARN] PWA配信履歴のクリーンアップ中に例外: {exc}", file=sys.stderr)
            return

        data = r.json()
        for page in data.get("results", []):
            try:
                del_res = requests.patch(
                    f"{API_BASE}/pages/{page['id']}",
                    headers=_headers(),
                    json={"archived": True},
                    timeout=30,
                )
                if del_res.ok:
                    deleted += 1
                else:
                    print(f"[WARN] PWA配信履歴の削除失敗 status={del_res.status_code}", file=sys.stderr)
            except requests.RequestException as exc:
                print(f"[WARN] PWA配信履歴の削除中に例外: {exc}", file=sys.stderr)

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    print(f"[PWA-HISTORY-CLEANUP] retention_days={retention_days} deleted={deleted}")
