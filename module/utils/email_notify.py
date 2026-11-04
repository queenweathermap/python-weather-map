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

# メール本文に添える参考リンク。HTMLメールなのでリンク文字列で見せ、長いURLは画面に出さない。
REFERENCE_LINKS = [
    ("気象庁 専門家向け資料", "https://www.jma.go.jp/jma/kishou/know/expert/index.html"),
    ("気象庁 防災情報", "https://www.jma.go.jp/bosai/#pattern=default&area_type=japan&area_code=010000"),
    ("気象庁 天気予報", "https://www.jma.go.jp/bosai/forecast/"),
    ("気象庁 気象衛星", "https://www.jma.go.jp/bosai/map.html#5/34.5/137/&elem=ir&contents=himawari"),
    ("気象庁 波浪実況・予想図", "https://www.data.jma.go.jp/waveinf/tile/jp/#zoom:4/lat:34.000000/lon:135.000000/mapheight:600/colordepth:normal/element:wave"),
    ("国土交通省 水文水質データベース", "https://www1.river.go.jp/"),
    ("University of Wyoming", "https://weather.arcc.uwyo.edu/upperair/"),
    ("気象庁 ウィンドプロファイラ", "https://www.jma.go.jp/bosai/windprofiler/"),
]


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _reference_links_html() -> str:
    rows = "<br>".join(
        f'🔗 <a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(label)}</a>'
        for label, url in REFERENCE_LINKS
    )
    return (
        '<p style="font-size:13px;line-height:1.9;margin-top:18px;">'
        f"参考リンク<br>{rows}</p>"
    )


def _build_html(lead: str, member_url: str, extra: str) -> str:
    return (
        f"<p>{html.escape(lead)}</p>"
        f'<p><a href="{html.escape(member_url)}">会員ページで天気図を見る</a></p>'
        f"{extra}"
        f"{_reference_links_html()}"
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
