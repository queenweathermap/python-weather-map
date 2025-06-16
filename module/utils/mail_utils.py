# module/utils/mail_utils.py
# ===============================================
# メール送信ユーティリティ（SMTP/添付ファイル対応・.env運用）
# -----------------------------------------------
# ・テキスト本文、件名、添付ファイル付きで送信可能
# ・.envの設定 or 引数でSMTP情報を柔軟に指定可
# ・複数アドレス送信、CC/BCC、HTMLメール、など拡張もしやすい構成
# -----------------------------------------------
# 必要パッケージ:
#   pip install python-dotenv
# -----------------------------------------------
# 利用例:
#   from module.utils.mail_utils import send_mail
#   send_mail("recipient@example.com", "テスト件名", "本文テスト", "添付ファイルパス.jpg")
# -----------------------------------------------
# 2025-06-17 by ChatGPT
# ===============================================

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# ------------------------------------------------
# .envの自動読込（グローバルで一度だけOK）
# ------------------------------------------------
load_dotenv()

def send_mail(
    to_addr,
    subject,
    body,
    attachment_path=None,
    from_addr=None,
    smtp_server=None,
    smtp_port=None,
    smtp_user=None,
    smtp_password=None,
    cc_addrs=None,
    bcc_addrs=None,
    is_html=False,
):
    """
    SMTPサーバ経由でメールを送信（テキスト/HTML/添付ファイル可）
    to_addr : 宛先アドレス（str またはリスト可）
    subject : 件名
    body    : 本文（プレーンテキスト or HTML）
    attachment_path: 添付ファイルパス（省略可）
    from_addr : 差出人（省略時は.envから自動取得）
    cc_addrs, bcc_addrs : CC/BCCアドレス（省略可・リスト可）
    is_html  : HTMLメールとして送信する場合True
    """
    # 設定の取得（優先順：引数→.env）
    from_addr = from_addr or os.environ.get("MAIL_FROM")
    smtp_server = smtp_server or os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = int(smtp_port or os.environ.get("MAIL_PORT", 587))
    smtp_user = smtp_user or os.environ.get("MAIL_USER")
    smtp_password = smtp_password or os.environ.get("MAIL_PASS")

    # アドレス整形
    if isinstance(to_addr, str):
        to_addr = [to_addr]
    if cc_addrs and isinstance(cc_addrs, str):
        cc_addrs = [cc_addrs]
    if bcc_addrs and isinstance(bcc_addrs, str):
        bcc_addrs = [bcc_addrs]
    recipients = to_addr + (cc_addrs or []) + (bcc_addrs or [])

    # メール構築
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addr)
    msg["Subject"] = subject
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg.attach(MIMEText(body, "html" if is_html else "plain"))

    # 添付ファイル（オプション）
    if attachment_path:
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read())
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(attachment_path),
            )
            msg.attach(part)

    # SMTP送信
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg, from_addr=from_addr, to_addrs=recipients)
    print("✅ メール送信完了")

# ------------------------------------------------
# 使い方例
# send_mail(
#   to_addr="recipient@example.com",
#   subject="テスト件名",
#   body="本文テスト",
#   attachment_path="添付ファイルパス.jpg"
# )
# ------------------------------------------------

# ---- 日本語コメント多めのヘッダで安心・拡張性重視 ----
# ・CC/BCC、HTMLメール送信にも柔軟対応
# ・.envと引数、どちらでも設定指定可能
# ・環境変数例:
#   MAIL_FROM, MAIL_SMTP_SERVER, MAIL_PORT, MAIL_USER, MAIL_PASS
# ・例外処理やロギングは用途に応じて追加
# ・メール大量送信/業務用はAPI（SendGrid等）併用も検討
