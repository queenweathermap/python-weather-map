# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/mail_utils.py
# -----------------------------------------------------------------------------
# SMTPメール送信（添付/HTML/複数宛先/再試行/詳細デバッグ/保存なし運用）
# - 587(STARTTLS) と 465(SMTPS) を自動フォールバック
# - EHLO → STARTTLS → EHLO → AUTH の正しい順序
# - エンベロープFrom（Return-Path）= 認証ユーザー を強制
# - MAIL_DEBUG=1 で SMTPlib の生ログを有効化
# =============================================================================
import os
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.headerregistry import Address
from email.utils import formataddr
from typing import Iterable, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

def _ensure_list(x) -> List[str]:
    if x is None: return []
    if isinstance(x, (list, tuple)): return list(x)
    return [str(x)]

def _build_message(
    mail_from: str,
    to_addrs: Iterable[str],
    subject: str,
    body: str,
    is_html: bool,
    cc_addrs: Iterable[str],
    attachments: List[Tuple[str, bytes, str]],
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Address(display_name="", username=mail_from.split("@")[0], domain=mail_from.split("@")[1])) , mail_from))
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs: msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

    for name, blob, ctype in attachments:
        part = MIMEApplication(blob, Name=name)
        part.add_header("Content-Disposition", "attachment", filename=name)
        if ctype:
            part.add_header("Content-Type", ctype)
        msg.attach(part)
    return msg

def _connect_and_send(
    host: str,
    port: int,
    user: str,
    password: str,
    envelope_from: str,
    recipients: List[str],
    msg: MIMEMultipart,
    debug: bool,
) -> str:
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)

    try:
        if debug: server.set_debuglevel(1)
        localname = socket.getfqdn() or "localhost"
        server.ehlo(localname)
        if port != 465:
            server.starttls()
            server.ehlo(localname)

        server.login(user, password)
        server.sendmail(envelope_from, recipients, msg.as_string())
        return msg.get("Message-ID") or "(sent)"
    finally:
        try: server.quit()
        except Exception: pass

def send_mail(
    to_addrs=None,
    subject: str = "",
    body: str = "",
    *,
    attachment_paths: Optional[List[str]] = None,
    attachment_blobs: Optional[List[Tuple[str, bytes, str]]] = None,
    mail_from: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    cc_addrs: Optional[Iterable[str]] = None,
    bcc_addrs: Optional[Iterable[str]] = None,
    is_html: bool = False,
) -> str:
    # --- 環境変数統一名から読み込み ---
    mail_from  = mail_from  or os.environ.get("FROM_EMAIL", "")
    to_addrs   = to_addrs   or os.environ.get("TO_EMAIL", "")
    smtp_host  = smtp_host  or os.environ.get("SMTP_SERVER", "")
    smtp_port  = int(smtp_port or os.environ.get("SMTP_PORT", "587"))
    smtp_user  = smtp_user  or os.environ.get("SMTP_USERNAME", "")
    smtp_pass  = smtp_password or os.environ.get("SMTP_PASSWORD", "")
    debug      = os.environ.get("MAIL_DEBUG", "0") == "1"

    if not mail_from:  raise RuntimeError("FROM_EMAIL 未設定")
    if not smtp_host:  raise RuntimeError("SMTP_SERVER 未設定")
    if not smtp_user:  raise RuntimeError("SMTP_USERNAME 未設定")
    if not smtp_pass:  raise RuntimeError("SMTP_PASSWORD 未設定")

    to_list  = _ensure_list(to_addrs)
    cc_list  = _ensure_list(cc_addrs)
    bcc_list = _ensure_list(bcc_addrs)
    recipients = [a for a in (to_list + cc_list + bcc_list) if a]
    if not recipients:
        raise RuntimeError("宛先がありません")

    blobs: List[Tuple[str, bytes, str]] = list(attachment_blobs or [])
    if attachment_paths:
        for p in attachment_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"添付が見つかりません: {p}")
            with open(p, "rb") as f:
                blobs.append((os.path.basename(p), f.read(), "application/octet-stream"))

    msg = _build_message(
        mail_from=mail_from,
        to_addrs=to_list,
        subject=subject,
        body=body,
        is_html=is_html,
        cc_addrs=cc_list,
        attachments=blobs,
    )

    envelope_from = smtp_user
    from_domain = mail_from.split("@")[-1].lower()
    user_domain = smtp_user.split("@")[-1].lower()
    if from_domain != user_domain:
        print(f"[WARN] From({from_domain}) と SMTP_USERNAME({user_domain}) のドメインが不一致です。拒否される可能性があります。")

    ports = [smtp_port] if smtp_port in (465, 587) else [587, 465]
    last_err = None
    for attempt, port in enumerate(ports, start=1):
        try:
            print(f"[INFO] SMTP try#{attempt}: host={smtp_host} port={port} user={smtp_user}")
            mid = _connect_and_send(
                host=smtp_host,
                port=port,
                user=smtp_user,
                password=smtp_pass,
                envelope_from=envelope_from,
                recipients=recipients,
                msg=msg,
                debug=debug,
            )
            print(f"[OK] メール送信成功（port={port}）: Message-ID={mid}")
            return mid
        except Exception as e:
            print(f"[ERR] SMTP送信失敗（port={port}）: {e}")
            last_err = e

    raise RuntimeError(f"メール送信に失敗しました（{attempt}回試行）: {last_err}")
