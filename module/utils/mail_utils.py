# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/mail_utils.py
# -----------------------------------------------------------------------------
# SMTPメール送信（添付/HTML/複数宛先/再試行/詳細デバッグ/保存なし運用）
# - 587(STARTTLS) と 465(SMTPS) を自動フォールバック
# - EHLO → STARTTLS → EHLO → AUTH の正しい順序
# - エンベロープFrom（Return-Path）= 認証ユーザー を強制（ポリシー回避）
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
    # 見た目のFrom（ヘッダ）。実体のエンベロープは別で指定
    msg["From"] = formataddr((str(Address(display_name="", username=mail_from.split("@")[0], domain=mail_from.split("@")[1])) , mail_from))
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs: msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

    # 添付
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
    """
    指定ポートで接続して送信。成功で Message-ID を返す。
    465=SMTPS, それ以外はSMTP→STARTTLS。
    """
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

        # 実際のエンベロープFromを認証ユーザーで固定（Return-Path）
        server.sendmail(envelope_from, recipients, msg.as_string())
        try:
            # 返ってくるメッセージIDが無いこともあるのでヘッダから拾う
            mid = msg.get("Message-ID") or ""
        except Exception:
            mid = ""
        return mid or "(sent)"
    finally:
        try: server.quit()
        except Exception: pass

def send_mail(
    to_addrs,
    subject: str,
    body: str,
    *,
    attachment_paths: Optional[List[str]] = None,
    attachment_blobs: Optional[List[Tuple[str, bytes, str]]] = None,  # (filename, bytes, mimetype)
    mail_from: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    cc_addrs: Optional[Iterable[str]] = None,
    bcc_addrs: Optional[Iterable[str]] = None,
    is_html: bool = False,
) -> str:
    """
    送信メイン。成功時 Message-ID 風の識別子を返す／失敗時 RuntimeError。
    """
    # --- env / 引数解決 ---
    mail_from  = mail_from  or os.environ.get("MAIL_FROM", "")
    smtp_host  = smtp_host  or os.environ.get("SMTP_HOST", "")
    smtp_port  = int(smtp_port or os.environ.get("SMTP_PORT", "587"))
    smtp_user  = smtp_user  or os.environ.get("SMTP_USER", "")
    smtp_pass  = smtp_password or os.environ.get("SMTP_PASS", "")
    debug      = os.environ.get("MAIL_DEBUG", "0") == "1"

    if not mail_from:  raise RuntimeError("MAIL_FROM 未設定")
    if not smtp_host:  raise RuntimeError("SMTP_HOST 未設定")
    if not smtp_user:  raise RuntimeError("SMTP_USER 未設定")
    if not smtp_pass:  raise RuntimeError("SMTP_PASS 未設定")

    to_list  = _ensure_list(to_addrs)
    cc_list  = _ensure_list(cc_addrs)
    bcc_list = _ensure_list(bcc_addrs)
    recipients = [a for a in (to_list + cc_list + bcc_list) if a]

    if not recipients:
        raise RuntimeError("宛先がありません")

    # 添付（ファイルパス→bytes化）
    blobs: List[Tuple[str, bytes, str]] = list(attachment_blobs or [])
    if attachment_paths:
        for p in attachment_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"添付が見つかりません: {p}")
            with open(p, "rb") as f:
                blobs.append((os.path.basename(p), f.read(), "application/octet-stream"))

    # メッセージ構築
    msg = _build_message(
        mail_from=mail_from,
        to_addrs=to_list,
        subject=subject,
        body=body,
        is_html=is_html,
        cc_addrs=cc_list,
        attachments=blobs,
    )

    # ポリシー回避のため、エンベロープFromは “認証ユーザー” に固定
    # （= 送信サーバが許可したドメインのFrom/Return-Path整合）
    envelope_from = smtp_user

    # From と 認証ユーザーのドメインを合わせるのが基本（明示チェック）
    from_domain = mail_from.split("@")[-1].lower()
    user_domain = smtp_user.split("@")[-1].lower()
    if from_domain != user_domain:
        print(f"[WARN] From({from_domain}) と SMTP_USER({user_domain}) のドメインが不一致です。拒否される可能性があります。")

    # 2回リトライ（587→465 の順）
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
        except smtplib.SMTPResponseException as e:
            # サーバが返した応答コードをそのまま表示
            print(f"[ERR] SMTP {e.smtp_code} {e.smtp_error}")
            last_err = e
        except Exception as e:
            print(f"[ERR] SMTP送信失敗（port={port}）: {e}")
            last_err = e

    raise RuntimeError(f"メール送信に失敗しました（{attempt}回試行）: {last_err}")
