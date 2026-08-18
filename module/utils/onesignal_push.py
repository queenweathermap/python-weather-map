# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/onesignal_push.py
#
# 有料配信（PWA/メールログイン購読者）向け: OneSignal経由でWeb Pushを送る。
# 対象は external_id にメールアドレスを設定して登録されている前提
# （177chart.com側のOneSignal JS SDK初期化時に setExternalUserId(email) する）。
#
# 必要な環境変数
#   ONESIGNAL_APP_ID
#   ONESIGNAL_REST_API_KEY
# =============================================================================

from __future__ import annotations

import os
import sys

import requests

API_BASE = "https://onesignal.com/api/v1/notifications"
REQUEST_TIMEOUT_SECONDS = 30

# OneSignalは1リクエストあたりの宛先数に上限があるため、多い場合は分割送信する。
BATCH_SIZE = 2000


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
        "Authorization": f"Key {_must_env('ONESIGNAL_REST_API_KEY')}",
        "Content-Type": "application/json",
    }


def _send_batch(emails: list, title: str, message: str, url: str | None) -> bool:
    payload = {
        "app_id": _must_env("ONESIGNAL_APP_ID"),
        "include_aliases": {"external_id": emails},
        "target_channel": "push",
        "headings": {"en": title, "ja": title},
        "contents": {"en": message, "ja": message},
    }
    if url:
        payload["url"] = url

    try:
        r = requests.post(API_BASE, headers=_headers(), json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: OneSignal push送信中に例外: {exc}", file=sys.stderr)
        return False

    if 200 <= r.status_code < 300:
        return True

    print(f"ERROR: OneSignal push送信失敗 status={r.status_code} body={r.text[:500]}", file=sys.stderr)
    return False


def send_push_to_all(emails: list, title: str, message: str, url: str | None = None) -> None:
    """対象メールアドレス（external_id）全員へWeb Pushを送る。
    1バッチの失敗が他のバッチを止めないようにする。"""
    if not emails:
        print("[INFO] OneSignal push対象なし（emailsが空）")
        return

    for i in range(0, len(emails), BATCH_SIZE):
        batch = emails[i : i + BATCH_SIZE]
        ok = _send_batch(batch, title, message, url)
        print(f"PUSH {'OK' if ok else 'FAILED'}: {len(batch)}件（{i + 1}〜{i + len(batch)}件目）")
