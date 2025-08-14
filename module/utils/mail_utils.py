# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/mail_utils.py
# -----------------------------------------------------------------------------
# SMTPメール送信（添付/HTML/複数宛先/再試行/詳細デバッグ/保存なし運用）+ Slack同報通知
#
# 統一環境変数:
#   FROM_EMAIL       : 差出人（表示用 From）
#   TO_EMAIL         : 既定の宛先（send_mail引数で上書き可）
#   SMTP_SERVER      : SMTPホスト（例: smtp.gmail.com）
#   SMTP_PORT        : 587(STARTTLS) / 465(SSL)
#   SMTP_USERNAME    : 認証ユーザー（Return-Path/Envelope-From に使用）
#   SMTP_PASSWORD    : 認証パスワード（Gmailは“アプリパスワード”）
#   MAIL_DEBUG       : "1"でsmtplibのデバッグログ
#
# Slack 環境変数（任意: 設定があれば自動通知）
#   SLACK_BOT_TOKEN  : Bot User OAuth Token (xoxb-...)
#   SLACK_CHANNEL_ID : 投稿先チャンネルID
#
# 機能:
#   - 587(STARTTLS) と 465(SSL) の自動フォールバック
#   - EHLO → STARTTLS → EHLO → AUTH の正しい順序
#   - エンベロープFrom(Return-Path) = SMTP_USERNAME を強制
#   - 送信成功/失敗を Slack に同報（設定がある場合）
# =============================================================================
import os
import smtplib
import socket
from typing import Iterable, List, Optional, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.headerregistry import Address
from email.utils import formataddr, formatdate
from dotenv import load_dotenv

load_dotenv()


# -----------------------------------------------------------------------------
# 内部ユーティリティ
# -----------------------------------------------------------------------------
def _ensure_list(x) -> List[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
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
    # 表示用 From（エンベロープFromは別で指定）
    disp = Address(display_name="", username=mail_from.split("@")[0], domain=mail_from.split("@")[1])
    msg["From"] = formataddr((str(disp), mail_from))
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
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
    """指定ポートで接続して送信。成功で Message-ID を返す。465=SMTPS, その他=STARTTLS。"""
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)

    try:
        if debug:
            server.set_debuglevel(1)
        localname = socket.getfqdn() or "localhost"
        server.ehlo(localname)
        if port != 465:
            server.starttls()
            server.ehlo(localname)

        server.login(user, password)
        server.sendmail(envelope_from, recipients, msg.as_string())

        return msg.get("Message-ID") or "(sent)"
    finally:
        try:
            server.quit()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Slack 通知（send_slack_text があれば利用／無ければWeb API直叩き）
# -----------------------------------------------------------------------------
def _notify_slack(subject: str, recipients: List[str], success: bool, error: Optional[str] = None):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not (token and channel):
        return  # 設定がなければ何もしない

    text = (
        f"{'✅' if success else '❌'} *Mail {'sent' if success else 'failed'}*\n"
        f"*Subject*: {subject}\n"
        f"*To*: {', '.join(recipients)}"
    )
    if not success and error:
        text += f"\n*Error*: ```{error[:900]}```"

    # 既存の slack_utils があれば優先使用
    try:
        from module.utils.slack_utils import send_slack_text  # type: ignore
        send_slack_text(channel=channel, message=text)
        return
    except Exception:
        pass

    # 直接 Web API
    try:
        import json
        import urllib.request

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": channel, "text": text}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            _ = resp.read()
    except Exception as e:
        print(f"[WARN] Slack通知に失敗: {e}")


# -----------------------------------------------------------------------------
# 公開関数
# -----------------------------------------------------------------------------
def send_mail(
    to_addrs=None,
    subject: str = "",
    body: str = "",
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
    メール送信（成功時に Slack 同報通知）。成功時 Message-ID 風の識別子を返す／失敗時 RuntimeError。
    """
    # --- 環境変数（統一名）を既定値として適用 ---
    mail_from = mail_from or os.environ.get("FROM_EMAIL", "")
    to_addrs = to_addrs or os.environ.get("TO_EMAIL", "")
    smtp_host = smtp_host or os.environ.get("SMTP_SERVER", "")
    smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", "587"))
    smtp_user = smtp_user or os.environ.get("SMTP_USERNAME", "")
    smtp_pass = smtp_password or os.environ.get("SMTP_PASSWORD", "")
    debug = os.environ.get("MAIL_DEBUG", "0") == "1"

    if not mail_from:
        raise RuntimeError("FROM_EMAIL 未設定")
    if not smtp_host:
        raise RuntimeError("SMTP_SERVER 未設定")
    if not smtp_user:
        raise RuntimeError("SMTP_USERNAME 未設定")
    if not smtp_pass:
        raise RuntimeError("SMTP_PASSWORD 未設定")

    to_list = _ensure_list(to_addrs)
    cc_list = _ensure_list(cc_addrs)
    bcc_list = _ensure_list(bcc_addrs)
    recipients = [a for a in (to_list + cc_list + bcc_list) if a]
    if not recipients:
        raise RuntimeError("宛先がありません")

    # 添付の読み込み（パス→bytes化）
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

    # エンベロープFromは認証ユーザーで固定（Return-Path整合）
    envelope_from = smtp_user

    # ドメイン不一致の注意喚起
    from_domain = mail_from.split("@")[-1].lower()
    user_domain = smtp_user.split("@")[-1].lower()
    if from_domain != user_domain:
        print(f"[WARN] From({from_domain}) と SMTP_USERNAME({user_domain}) のドメインが不一致です。拒否される可能性があります。")

    # 2回リトライ（587 → 465）
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
            # Slack 同報（成功）
            _notify_slack(subject=subject, recipients=recipients, success=True)
            return mid
        except smtplib.SMTPResponseException as e:
            err = f"SMTP {e.smtp_code} {e.smtp_error}"
            print(f"[ERR] {err}")
            last_err = err
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"[ERR] SMTP送信失敗（port={port}）: {err}")
            last_err = err

    # Slack 同報（失敗）
    _notify_slack(subject=subject, recipients=recipients, success=False, error=str(last_err) if last_err else None)
    raise RuntimeError(f"メール送信に失敗しました（{attempt}回試行）: {last_err}")
