import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# .env読込（既にどこかで読んでいれば不要）
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
    from_addr = from_addr or os.environ.get("MAIL_FROM")
    smtp_server = smtp_server or os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = int(smtp_port or os.environ.get("MAIL_PORT", 587))
    smtp_user = smtp_user or os.environ.get("MAIL_USER")
    smtp_password = smtp_password or os.environ.get("MAIL_PASS")

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read())
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(attachment_path),
            )
            msg.attach(part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    print("✅ メール送信完了")

# 例:
# send_mail("recipient@example.com", "テスト件名", "本文テスト", "添付ファイルパス.jpg")
