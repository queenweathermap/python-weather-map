"""
JMA 防災情報アドバイザー向け 専門天気図（tgv）を
GitHub Actions 上で自動取得し、メールで送信するスクリプト。

【重要】
- 認証は Cookie ではなく「Authorization: Basic xxx」を使用
- Authorization の値は GitHub Secrets（JMA_AUTH_BASIC）から取得
- 個人利用・非公開前提
"""

import os
import requests
from email.message import EmailMessage
import smtplib
from pathlib import Path
from datetime import datetime


# =========================================================
# 取得したい専門天気図の定義
# =========================================================
# Safari のネットワークタブで確認した URL をそのまま使う
MAPS = [
    {
        "title": "GSMWide 300hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002000_RJTD_010000.png",
        "filename": "GSMWide_300hPa.png",
    },
    {
        "title": "MSMNarrow 500hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/500/images/VIEW500200_RJTD_030300.png",
        "filename": "MSMNarrow_500hPa.png",
    },
    {
        "title": "LFMNarrow 850hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW850200_RJTD_030500.png",
        "filename": "LFMNarrow_850hPa.png",
    },
]


# =========================================================
# 必須環境変数を安全に読むための関数
# =========================================================
def must_env(name: str) -> str:
    """
    環境変数が存在しない場合は即エラーにする。
    GitHub Actions での設定漏れを早期に検知するため。
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# =========================================================
# 専門天気図を取得する処理
# =========================================================
def fetch_images() -> list[Path]:
    """
    JMA の専門天気図（PNG）を Authorization 付きで取得し、
    ローカルファイルとして保存する。
    """
    # Safari で確認した「Authorization: Basic xxxx」をそのまま使う
    auth_basic = must_env("JMA_AUTH_BASIC")

    headers = {
        # ★ここが最大のポイント★
        "Authorization": auth_basic,

        # User-Agent が無いと弾かれるケースを避けるため明示
        "User-Agent": "Mozilla/5.0",

        # Safari の挙動に合わせた Referer
        "Referer": "https://www.jma.go.jp/bosai/tgv/LFM/",
    }

    saved_files: list[Path] = []

    for m in MAPS:
        print(f"Fetching: {m['title']}")
        response = requests.get(
            m["url"],
            headers=headers,
            timeout=30,
        )

        # 401 / 403 / 404 などはここで例外になる
        response.raise_for_status()

        path = Path(m["filename"])
        path.write_bytes(response.content)
        saved_files.append(path)

    return saved_files


# =========================================================
# メール送信処理
# =========================================================
def send_mail(files: list[Path]) -> None:
    """
    取得した PNG を添付してメール送信する。
    SMTP 設定は既存 run_jma.yml と共通。
    """
    mail_from = must_env("FROM_EMAIL")
    mail_to = must_env("TO_EMAIL")

    smtp_server = must_env("SMTP_SERVER")
    smtp_port = int(must_env("SMTP_PORT"))
    smtp_user = must_env("SMTP_USERNAME")
    smtp_pass = must_env("SMTP_PASSWORD")

    subject_prefix = os.getenv("EMAIL_SUBJECT_PREFIX", "JMA")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    msg = EmailMessage()
    msg["Subject"] = f"{subject_prefix} 専門天気図（tgv） {now}"
    msg["From"] = mail_from
    msg["To"] = mail_to

    msg.set_content(
        "防災情報アドバイザー向け 専門天気図（tgv）を自動取得しました。\n"
        "・個人利用\n"
        "・非公開\n"
        "・GitHub Actions による自動送信\n"
    )

    # PNG をすべて添付
    for f in files:
        msg.add_attachment(
            f.read_bytes(),
            maintype="image",
            subtype="png",
            filename=f.name,
        )

    # SMTP 送信
    with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)


# =========================================================
# エントリーポイント
# =========================================================
if __name__ == "__main__":
    print("Start fetching JMA TGV maps")

    files = fetch_images()

    print("Fetched files:", [f.name for f in files])

    send_mail(files)

    print("Mail sent successfully")
