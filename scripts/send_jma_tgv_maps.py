"""
JMA 防災情報アドバイザー向け「専門天気図（tgv）」を
GitHub Actions 上で自動取得し、メールで送信するスクリプト。

【設計方針（重要）】
- Safari の Network タブで観測された挙動を忠実に再現する
- GSM / MSM / LFM すべてで
    Authorization: Basic xxxx
    Referer: モデル別URL
  が付与されていることを前提とする
- 個人利用・非公開前提

【対応済みの落とし穴】
- キャッシュ差異による 401 回避
- Referer 不一致による 401 回避
- GitHub Secrets の改行混入対策
"""

import os
import requests
from email.message import EmailMessage
import smtplib
from pathlib import Path
from datetime import datetime


# ============================================================
# 取得したい専門天気図の定義
# ============================================================
# Safari のネットワークタブで確認した PNG URL をそのまま使う
MAPS = [
    {
        "title": "GSMWide 300hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002003_RJTD_030000.png",
        "filename": "GSMWide_300hPa.png",
    },
    {
        "title": "MSMNarrow 700hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/700/images/VIEW700201_RJTD_030300.png",
        "filename": "MSMNarrow_700hPa.png",
    },
    {
        "title": "LFMNarrow 850hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW860201_RJTD_030600.png",
        "filename": "LFMNarrow_850hPa.png",
    },
]


# ============================================================
# 環境変数取得（必須チェック付き）
# ============================================================
def must_env(name: str) -> str:
    """
    環境変数が未設定の場合は即エラーにする。
    GitHub Actions の Secrets 設定漏れを早期検出するため。
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ============================================================
# URLに応じて Safari と同じ HTTP ヘッダを生成
# ============================================================
def headers_for(url: str) -> dict:
    """
    Safari の実際の通信を再現したヘッダを返す。

    - Authorization: Basic は全モデル共通で付与
    - Referer はモデル別に切り替える（401回避の最重要ポイント）
    """
    auth_basic = must_env("JMA_AUTH_BASIC").strip()

    # モデル別 Referer 切替
    if "/tgv/data/GSMWide/" in url:
        referer = "https://www.jma.go.jp/bosai/tgv/GSM/"
    elif "/tgv/data/MSMNarrow/" in url:
        referer = "https://www.jma.go.jp/bosai/tgv/MSM/"
    elif "/tgv/data/LFMNarrow/" in url:
        referer = "https://www.jma.go.jp/bosai/tgv/LFM/"
    else:
        referer = "https://www.jma.go.jp/bosai/tgv/"

    return {
        # Safari で観測された認証方式
        "Authorization": auth_basic,

        # User-Agent は必須（無いと弾かれるケースあり）
        "User-Agent": "Mozilla/5.0",

        # Referer 不一致は 401 の原因になる
        "Referer": referer,

        # キャッシュ挙動差による不安定さを回避
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# ============================================================
# 専門天気図を取得してローカルに保存
# ============================================================
def fetch_images() -> list[Path]:
    """
    MAPS で定義された PNG をすべて取得する。
    """
    saved_files: list[Path] = []

    for m in MAPS:
        print(f"Fetching: {m['title']}")
        headers = headers_for(m["url"])

        response = requests.get(
            m["url"],
            headers=headers,
            timeout=30,
        )

        # 401 / 403 / 404 等はここで例外として止まる
        response.raise_for_status()

        path = Path(m["filename"])
        path.write_bytes(response.content)
        saved_files.append(path)

    return saved_files


# ============================================================
# メール送信処理
# ============================================================
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
        "防災情報アドバイザー向け 専門天気図（tgv）です。\n"
        "・Safariと同一条件で取得\n"
        "・個人利用\n"
        "・非公開\n"
    )

    # 画像をすべて添付
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


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    print("=== Start fetching JMA TGV maps ===")

    files = fetch_images()
    print("Fetched files:", [f.name for f in files])

    send_mail(files)

    print("=== Mail sent successfully ===")
