# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/email_notify.py
#
# 会員ページで「メールで受け取る」をONにした人へ、天気図の配信お知らせメールを送る。
# 画像は添付しない（全部入り天気図は1枚50MB超のため）。会員ページへのリンクだけを送る。
# 送信はResend（Worker側のマジックリンクメールと同じアカウント）。
#
# 必要な環境変数（未設定なら何もせずスキップ）
#   RESEND_API_KEY
#   RESEND_FROM_EMAIL
# =============================================================================

from __future__ import annotations

import html
import os
from typing import List

import requests

RESEND_BATCH_API = "https://api.resend.com/emails/batch"
REQUEST_TIMEOUT_SECONDS = 30
BATCH_SIZE = 100  # Resendのbatch APIは1リクエスト100通まで


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _build_html(lead: str, member_url: str, extra: str) -> str:
    return (
        f"<p>{html.escape(lead)}</p>"
        f'<p><a href="{html.escape(member_url)}">会員ページで天気図を見る</a></p>'
        f"{extra}"
        '<hr style="border:none;border-top:1px solid #ddd;margin:20px 0;">'
        '<p style="font-size:12px;color:#666;line-height:1.7;">'
        "このメールは、会員ページで「メールで受け取る」をONにしている方へお送りしています。<br>"
        "天気図の画像は添付していません。上のリンクから会員ページを開いてご覧ください"
        "（ログインが必要な場合があります）。<br>"
        "配信を止めたいときは、会員ページの「メールをオフにする」ボタンを押してください。"
        "プッシュ通知とは別の設定です。"
        "</p>"
    )


def send_notice_emails(
    emails: List[str],
    *,
    subject: str,
    lead: str,
    member_url: str,
    extra_html: str = "",
) -> int:
    """emailsの各宛先へ1通ずつ送る(宛先同士は見えない)。送信した通数を返す。"""
    api_key = _env("RESEND_API_KEY")
    sender = _env("RESEND_FROM_EMAIL")
    if not emails or not api_key or not sender:
        if emails:
            print("[INFO] RESEND_API_KEY/RESEND_FROM_EMAIL 未設定のためメール配信をスキップ")
        return 0

    body_html = _build_html(lead, member_url, extra_html)
    sent = 0
    for i in range(0, len(emails), BATCH_SIZE):
        chunk = emails[i : i + BATCH_SIZE]
        payload = [
            {"from": sender, "to": [e], "subject": subject, "html": body_html}
            for e in chunk
        ]
        r = requests.post(
            RESEND_BATCH_API,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if r.status_code >= 400:
            print(f"[WARN] Resend batch失敗 {r.status_code}: {r.text[:300]}")
            continue
        sent += len(chunk)
    print(f"[OK] 天気図メール送信 {sent}/{len(emails)}通")
    return sent
