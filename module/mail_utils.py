import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os

def send_mail(
    to_addr,
    subject,
    body,
    attachment_path=None,
    from_addr=None,
    smtp_server=None,
    smtp_port=465,
    smtp_user=None,
    smtp_password=None
):
    from_addr = from_addr or os.environ["MAIL_FROM"]
    smtp_server = smtp_server or os.environ["MAIL_SMTP_SERVER"]
    smtp_user = smtp_user or os.environ["MAIL_USER"]
    smtp_password = smtp_password or os.environ["MAIL_PASS"]
    smtp_port = int(os.environ.get("MAIL_PORT", smtp_port))

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        with open(attachment_path, "rb") as f:
            att = MIMEApplication(f.read())
            att.add_header("Content-Disposition", "attachment", filename=os.path.basename(attachment_path))
            msg.attach(att)

    with smtplib.SMTP(smtp_server, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)
    print("✅ メール送信完了")

# 使い方例
# from module.mail_utils import send_mail
# send_mail("宛先アドレス", "件名", "本文", "ファイルパス")
