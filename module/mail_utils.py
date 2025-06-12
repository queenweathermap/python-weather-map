# module/mail_utils.py
# ===============================================
# メール送信ユーティリティ（SMTP/添付ファイル対応・.env運用）
# -----------------------------------------------
# ・テキスト本文、件名、添付ファイル付きで送信可能
# ・.envの設定 or 引数でSMTP情報を柔軟に指定可
# ・複数アドレスやHTMLメール等、拡張も容易
# -----------------------------------------------
# 必要パッケージ: python-dotenv
#   pip install python-dotenv
# -----------------------------------------------
# 利用例:
#   from module.mail_utils import send_mail
#   send_mail("recipient@example.com", "テスト件名", "本文テスト", "添付ファイルパス.jpg")
# ===============================================

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# --- .envの自動読込（他で実施済なら不要） ---
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
):
    """
    SMTPサーバを利用し、メールを送信するユーティリティ
    - .envのMAIL_xxx設定 or 引数で送信元・SMTP設定指定
    - 添付ファイル送信も対応
    """
    # .envや引数から設定を取得
    from_addr = from_addr or os.environ.get("MAIL_FROM")
    smtp_server = smtp_server or os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = int(smtp_port or os.environ.get("MAIL_PORT", 587))
    smtp_user = smtp_user or os.environ.get("MAIL_USER")
    smtp_password = smtp_password or os.environ.get("MAIL_PASS")

    # メールメッセージ構築
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

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
        server.send_message(msg)
    print("✅ メール送信完了")

# --- 使い方例（テスト用）---
# send_mail("recipient@example.com", "テスト件名", "本文テスト", "添付ファイルパス.jpg")
# 使い方サンプルの追加」「CC/BCC対応」「HTMLメール」など拡張したい場合は相談
