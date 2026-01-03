import os
import requests
from email.message import EmailMessage
import smtplib
from pathlib import Path
from datetime import datetime

MAPS = [
    {
        "title": "GSMWide 300hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002000_RJTD_010000.png",
        "filename": "GSMWide_300hPa_VIEW3002000_RJTD_010000.png",
    },
    {
        "title": "MSMNarrow 500hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/500/images/VIEW500200_RJTD_030300.png",
        "filename": "MSMNarrow_500hPa_VIEW500200_RJTD_030300.png",
    },
    {
        "title": "LFMNarrow 850hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW850200_RJTD_030500.png",
        "filename": "LFMNarrow_850hPa_VIEW850200_RJTD_030500.png",
    },
]

def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v

def fetch_images() -> list[Path]:
    files: list[Path] = []
    for m in MAPS:
        r = requests.get(m["url"], timeout=30)
        r.raise_for_status()
        p = Path(m["filename"])
        p.write_bytes(r.content)
        files.append(p)
    return files

def send_mail(files: list[Path]) -> None:
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
        "防災情報アドバイザー向け専門天気図（tgv）を自動取得して添付します。\n"
        "（個人利用・非公開）\n"
    )

    for f in files:
        msg.add_attachment(
            f.read_bytes(),
            maintype="image",
            subtype="png",
            filename=f.name
        )

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

if __name__ == "__main__":
    files = fetch_images()
    send_mail(files)
    print("Sent:", [f.name for f in files])
