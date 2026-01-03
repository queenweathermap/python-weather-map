"""
JMA 防災情報アドバイザー向け「専門天気図（tgv）」を
GitHub Actions 上で自動取得し、メールで送信するスクリプト（Safari互換）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【このスクリプトの狙い】
- Safari の Network タブで確認した挙動（Authorization + Referer）を再現
- GitHub Actions（サーバ実行）でも同じPNGを取得できるようにする
- 取得した PNG をメールに添付して送信する

【認証の扱い（重要）】
このサイトは Basic 認証相当の Authorization ヘッダが必要です。
運用上の安全性と柔軟性のため、以下の優先順位で認証情報を用意します。

(優先) 1) JMA_ADV_USER / JMA_ADV_PASS から毎回 Basic を生成
(予備) 2) JMA_AUTH_BASIC をそのまま利用（フォールバック）

→ これにより
  - USER/PASSを正として管理できる
  - Safariで観測したJMA_AUTH_BASICも残して比較・退避できる
  - どちらかが未設定でも止まりにくい（設定漏れ耐性）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【404対策（今回の失敗原因）】
- LFM の画像は VIEW860200 / VIEW860201 のどちらか片方しか無い時があります。
- そのため、まず指定URLを取りに行き、404だった場合だけ
  “200↔201 を入れ替えた代替URL” を自動で試します。
- GSM/MSM も将来同様の揺れが起きても使い回せるよう、
  汎用的に「末尾3桁が200/201なら入れ替える」処理も入れています。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import base64
import requests
from email.message import EmailMessage
import smtplib
from pathlib import Path
from datetime import datetime


# ============================================================
# 取得したい専門天気図（PNG）の定義
# ============================================================
# ここは「あなたが送りたい図」に合わせて差し替えます。
# URL は Safari のネットワークタブで取れたものをそのまま貼るのが確実です。
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
        # ここはどちらを置いてもOK（404時に自動で200↔201を試す）
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW860201_RJTD_030600.png",
        "filename": "LFMNarrow_850hPa.png",
    },
]


# ============================================================
# 環境変数の必須チェック
# ============================================================
def must_env(name: str) -> str:
    """
    必須の環境変数が未設定なら即エラーにして止める。
    GitHub Actions の Secrets 設定漏れを早期に検知するため。
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ============================================================
# Basic 認証（Authorization: Basic ...）の生成
# ============================================================
def make_basic_auth(user: str, password: str) -> str:
    """
    user:password を base64 して Authorization ヘッダ値を作る。
    例: "Basic YWR2...="
    """
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    """
    認証情報の用意（優先順位つき）
      1) JMA_ADV_USER / JMA_ADV_PASS があれば、そこから生成（推奨）
      2) なければ JMA_AUTH_BASIC をそのまま使う（フォールバック）

    Secrets に改行が混ざると認証が壊れるので strip() で吸収。
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")

    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())

    # フォールバック（Safariで拾った "Basic ...." を Secrets に入れている場合）
    return must_env("JMA_AUTH_BASIC").strip()


# ============================================================
# URL に応じて Safari と同じ Referer を切り替える
# ============================================================
def referer_for(url: str) -> str:
    """
    Safariで観測された Referer をモデル別に合わせる。
    Referer 不一致は 401 / 403 の原因になることがあるため重要。
    """
    if "/tgv/data/GSMWide/" in url:
        return "https://www.jma.go.jp/bosai/tgv/GSM/"
    if "/tgv/data/MSMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/MSM/"
    if "/tgv/data/LFMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/LFM/"
    return "https://www.jma.go.jp/bosai/tgv/"


def headers_for(url: str) -> dict:
    """
    Safari互換のヘッダを作る。
    - Authorization は get_auth_basic() で統一
    - Referer は URLごとに切替
    - Cache-Control/Pragma はキャッシュ差で挙動が変わるのを避けたい時に有効
    """
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer_for(url),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# ============================================================
# 404時の「代替URL」生成（200↔201 入れ替え）
# ============================================================
def make_alt_url_if_possible(url: str) -> str | None:
    """
    例：
      .../VIEW860201_RJTD_030600.png  ->  .../VIEW860200_RJTD_030600.png
      .../VIEW860200_RJTD_030600.png  ->  .../VIEW860201_RJTD_030600.png

    200/201 が含まれないURLの場合は None を返す。
    """
    if "VIEW" not in url:
        return None

    # よくあるケース：VIEWxxxx200 / VIEWxxxx201
    if "VIEW860201_" in url:
        return url.replace("VIEW860201_", "VIEW860200_")
    if "VIEW860200_" in url:
        return url.replace("VIEW860200_", "VIEW860201_")

    # 汎用化：末尾の "200_" / "201_" を入れ替え（他モデルでも効く可能性）
    # ただし誤爆を避けるため、"VIEW" の直後に出てくる箇所だけを想定。
    if "200_" in url:
        # 先に 200->201 を試す（元が200のとき）
        return url.replace("200_", "201_", 1)
    if "201_" in url:
        # 元が201のとき
        return url.replace("201_", "200_", 1)

    return None


def get_with_fallback(url: str) -> requests.Response:
    """
    通常取得 → 404 の場合のみ代替URLを試す。

    ・401/403 は「認証やRefererの問題」なので代替を試しても意味がない。
      → そのまま raise してログで原因を見つける。
    ・404 だけが今回の原因（ファイルが無い）
      → 200/201 を入れ替えたURLを試す
    """
    r = requests.get(url, headers=headers_for(url), timeout=30)

    # 正常または 401/403/500 等はここで判定
    if r.status_code != 404:
        r.raise_for_status()
        return r

    # 404 だけ、代替URLを試す
    alt = make_alt_url_if_possible(url)
    if not alt:
        r.raise_for_status()
        return r

    print(f"  404 Not Found. Try alternate: {alt}")
    r2 = requests.get(alt, headers=headers_for(alt), timeout=30)
    r2.raise_for_status()
    return r2


# ============================================================
# PNG 取得
# ============================================================
def fetch_images() -> list[Path]:
    """
    MAPS に定義された PNG を取得し、ファイルとして保存して返す。

    重要：
    - 404 の時だけ “200↔201 の代替” を自動で試すので
      LFM の揺れに強くなります。
    """
    saved_files: list[Path] = []

    for m in MAPS:
        url = m["url"]
        print(f"Fetching: {m['title']}")

        # ここで 404 対策付き取得
        r = get_with_fallback(url)

        path = Path(m["filename"])
        path.write_bytes(r.content)
        saved_files.append(path)

    return saved_files


# ============================================================
# メール送信
# ============================================================
def send_mail(files: list[Path]) -> None:
    """
    取得した PNG を添付してメール送信する。
    SMTP 設定は GitHub Secrets から受け取る（.env は不要）。
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
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）を自動取得しました。\n"
        "・個人利用・非公開\n"
        "・GitHub Actions 実行\n"
    )

    # PNG を添付
    for f in files:
        msg.add_attachment(
            f.read_bytes(),
            maintype="image",
            subtype="png",
            filename=f.name,
        )

    # SMTP（587 = STARTTLS）で送信
    # 587 は「SMTPで接続 → starttls()で暗号化 → login → send」
    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

    print("[MAIL] send_message() done")



# ============================================================
# メイン
# ============================================================
if __name__ == "__main__":
    print("=== Start fetching JMA TGV maps ===")

    files = fetch_images()
    print("Fetched files:", [f.name for f in files])

    send_mail(files)
    print("=== Mail sent successfully ===")
