# module/utils/mail_utils.py
# ===============================================
# メール送信ユーティリティ（SMTP/添付ファイル対応・.env運用）
# -----------------------------------------------
# ・テキスト/HTML、複数宛先、添付対応
# ・.envまたは引数から柔軟設定可
# -----------------------------------------------
# 必要パッケージ:
#   pip install python-dotenv
# -----------------------------------------------
# 利用例:
#   from module.utils.mail_utils import send_mail
#   send_mail(
#       to_addr="recipient@example.com",
#       subject="件名",
#       body="本文",
#       attachment_paths=["file.pdf"]
#   )
# ===============================================

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# --- .env 読み込み（他でも実施済でも安全） ---
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
    """SMTPメール送信（添付・HTML・複数宛先対応）"""
    from_addr = from_addr or os.environ.get("MAIL_FROM")
    smtp_server = smtp_server or os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = int(smtp_port or os.environ.get("MAIL_PORT", 587))
    smtp_user = smtp_user or os.environ.get("MAIL_USER")
    smtp_password = smtp_password or os.environ.get("MAIL_PASS")

    # --- メール構築 ---
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr if isinstance(to_addr, str) else ", ".join(to_addr)
    msg["Subject"] = subject
    if cc_addrs:
        msg["Cc"] = cc_addrs if isinstance(cc_addrs, str) else ", ".join(cc_addrs)
    recipients = [to_addr] if isinstance(to_addr, str) else to_addr
    if cc_addrs:
        recipients += cc_addrs if isinstance(cc_addrs, list) else [cc_addrs]
    if bcc_addrs:
        recipients += bcc_addrs if isinstance(bcc_addrs, list) else [bcc_addrs]

    msg.attach(MIMEText(body, "html" if is_html else "plain"))

    # --- 添付ファイル ---
    if attachment_paths:
        for path in attachment_paths:
            if not os.path.exists(path):
                print(f"[WARN] 添付ファイルが見つかりません: {path}")
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(path))
                part.add_header("Content-Disposition", "attachment", filename=os.path.basename(path))
                msg.attach(part)
                print(f"[OK] 添付: {path}")

    # --- SMTP送信 ---
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, recipients, msg.as_string())
        server.quit()
        print(f"[OK] メール送信成功: {recipients}")
    except Exception as e:
        print(f"[ERROR] メール送信失敗: {e}")
        raise
