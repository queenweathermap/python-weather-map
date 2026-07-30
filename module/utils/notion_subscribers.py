# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_subscribers.py
#
# 有料DM配信の購読者リスト（Notionデータベース）を読むユーティリティ。
# 書き込み（行の作成・更新）はCloudflare Worker側（Stripe Webhook）が行うため、
# ここでは読み取り専用。
#
# Status の種類:
#   active   ... Stripe課金中
#   beta     ... 無料のβtester（BETA_CUTOFFを過ぎたら自動的に配信対象から外れる）
#   admin    ... 運営者自身。課金なしで常に配信対象
#   lifetime ... 本格運用開始より前から参加してくれた人。課金なしで常に配信対象
#                （betaと違い期限なし。自己登録ルートは無く、Notionに手動で設定する）
#   canceled ... 配信対象外
#
# 必要な環境変数
#   NOTION_TOKEN                    （module/utils/notion_utils.py と共有）
#   NOTION_SUBSCRIBERS_DATABASE_ID
#
# 任意（DBプロパティ名が環境で違う場合の上書き）
#   NOTION_SUB_PROP_STATUS="Status"
#   NOTION_SUB_PROP_DISCORD_ID="Discord User ID"
# =============================================================================

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import List

import requests

NOTION_VERSION = "2025-09-03"
API_BASE = "https://api.notion.com/v1"

# 本格運用（課金必須）の開始日。Worker側 (src/index.ts) の BETA_CUTOFF と同じ日付。
JST = timezone(timedelta(hours=9))
BETA_CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=JST)

ELIGIBLE_STATUSES = ("active", "beta", "admin", "lifetime")


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


def _prop_status() -> str:
    return _env("NOTION_SUB_PROP_STATUS", "Status")


def _prop_discord_id() -> str:
    return _env("NOTION_SUB_PROP_DISCORD_ID", "Discord User ID")


def _raise_with_body(r: requests.Response) -> None:
    """Notion APIのエラーはbodyに具体的な理由(code/message)が入っているため、
    ステータスコードだけでなくbodyもログに残す。"""
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        raise requests.HTTPError(f"{e} body={r.text[:500]}", response=r) from None


def _resolve_data_source_id(db_id: str) -> str:
    """
    2025-09-03以降のNotion APIでは、データベースへの行の問い合わせは
    databases/{id}/query ではなく data_sources/{id}/query を使う必要がある
    （新しいデータベースはこの形式でないと400 Bad Requestになる）。
    そのためまずデータベースを取得し、直下のdata_sourceのidを得る。
    """
    r = requests.get(f"{API_BASE}/databases/{db_id}", headers=_headers(), timeout=30)
    _raise_with_body(r)
    data_sources = r.json().get("data_sources", [])
    if not data_sources:
        raise RuntimeError(f"NOTION_SUBSCRIBERS_DATABASE_ID={db_id} has no data_sources")
    return data_sources[0]["id"]


def _existing_select_options(data_source_id: str, prop_name: str) -> set:
    """
    新APIはselectのequalsフィルタに、実際にそのDBに存在しない選択肢名を
    渡すと400 validation_errorになる(旧APIは単に0件マッチだったが、
    新APIは厳格にスキーマを検証する)。ELIGIBLE_STATUSESの中にまだこの
    DBに無い選択肢(例:betaオプションを作っていない)が含まれていても
    落ちないよう、実在する選択肢だけに絞る。
    """
    r = requests.get(f"{API_BASE}/data_sources/{data_source_id}", headers=_headers(), timeout=30)
    _raise_with_body(r)
    prop = r.json().get("properties", {}).get(prop_name, {})
    options = (prop.get("select") or {}).get("options", [])
    return {opt.get("name", "") for opt in options}


def get_active_discord_ids() -> List[str]:
    """購読者データベースから配信対象（active/beta/admin/lifetime）のDiscord User IDを返す。
    ただしbetaはBETA_CUTOFFを過ぎたら対象外にする（Notion側のStatusは
    手動更新不要で、ここでの日付判定だけで自動的に配信が止まる）。"""
    db_id = _must_env("NOTION_SUBSCRIBERS_DATABASE_ID")
    data_source_id = _resolve_data_source_id(db_id)

    existing_options = _existing_select_options(data_source_id, _prop_status())
    statuses_to_query = [s for s in ELIGIBLE_STATUSES if s in existing_options]
    skipped = [s for s in ELIGIBLE_STATUSES if s not in existing_options]
    if skipped:
        print(f"[INFO] Status選択肢が未作成のため対象外: {skipped} (既存: {sorted(existing_options)})")
    if not statuses_to_query:
        raise RuntimeError(
            f"None of ELIGIBLE_STATUSES {ELIGIBLE_STATUSES} exist as '{_prop_status()}' "
            f"select options (existing: {sorted(existing_options)})"
        )

    payload = {
        "filter": {
            "or": [
                {"property": _prop_status(), "select": {"equals": status}}
                for status in statuses_to_query
            ]
        },
        "page_size": 100,
    }

    beta_still_open = datetime.now(JST) < BETA_CUTOFF

    ids: List[str] = []
    cursor = None

    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor

        r = requests.post(
            f"{API_BASE}/data_sources/{data_source_id}/query",
            headers=_headers(),
            json=body,
            timeout=30,
        )
        _raise_with_body(r)
        data = r.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            status = (props.get(_prop_status(), {}).get("select") or {}).get("name", "")
            if status == "beta" and not beta_still_open:
                continue

            rich_text = props.get(_prop_discord_id(), {}).get("rich_text", [])
            if rich_text:
                discord_id = rich_text[0].get("plain_text", "").strip()
                if discord_id:
                    ids.append(discord_id)

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    return ids
