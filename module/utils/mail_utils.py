# module/utils/mail_utils.py
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
#   from module.utils.mail_utils import send_mail
#   send_mail("recipient@example.com", "件名", "本文", ["添付ファイル.jpg"])
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
    attachment_paths=None,
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
    メールを送信する関数（複数添付ファイル対応・HTML可）

    Parameters:
    - to_addr: 送信先アドレス（str or list[str]）
    - subject: 件名（str）
    - body: 本文（str）
    - attachment_paths: 添付ファイルのパス一覧（list[str] or None）
    - from_addr: 差出人メールアドレス（None時は.envから）
    - smtp_server: SMTPサーバ（None時は.envから）
    - smtp_port: ポート番号（None時は.envから）
    - smtp_user: SMTPログインユーザー（None時は.envから）
    - smtp_password: SMTPログインパスワード（None時は.envから）
    - cc_addrs: CCアドレス（str or list[str] or None）
    - bcc_addrs: BCCアドレス（str or list[str] or None）
    - is_html: 本文をHTMLとして送信するか（bool）
    """


    # --- 引数 or 環境変数から情報取得 ---
    from_addr = from_addr or os.environ.get("MAIL_FROM")
    smtp_server = smtp_server or os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = int(smtp_port or os.environ.get("MAIL_PORT", 587))
    smtp_user = smtp_user or os.environ.get("MAIL_USER")
    smtp_password = smtp_password or os.environ.get("MAIL_PASS")

    # --- メール作成 ---
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr if isinstance(to_addr, str) else ", ".join(to_addr)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    # --- 添付ファイル（任意） ---
    if attachments:
        for path in attachments:
            if not os.path.exists(path):
                print(f"[WARN] 添付ファイルが見つかりません: {path}")
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(path))
                part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
                msg.attach(part)
                print(f"[OK] 添付ファイル: {path}")

    # --- SMTP送信 ---
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            server.ehlo()
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"[OK] メール送信成功: {to_addr}")
    except Exception as e:
        print(f"[ERROR] メール送信失敗: {e}")
        raise
