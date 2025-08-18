# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/mail_utils.py
# -----------------------------------------------------------------------------
# SMTPメール送信（複数添付/ZIP自動化/再試行/Slack同報・一回だけ）
#
# 既定の環境変数（統一名）
#   FROM_EMAIL        : 差出人（表示用 From）
#   TO_EMAIL          : 既定の宛先（引数で上書き可）
#   SMTP_SERVER       : 例 smtp.gmail.com
#   SMTP_PORT         : 587(STARTTLS) / 465(SSL)
#   SMTP_USERNAME     : 認証ユーザー（Return-Path/Envelope-From に使用）
#   SMTP_PASSWORD     : 認証パスワード（Gmailはアプリパスワード）
#   MAIL_SUBJECT_PREFIX : 件名の先頭につける文字列（例 "[Japan]"）
#   MAIL_DEBUG        : "1" で smtplib のデバッグ
#
# オプション環境変数
#   MAIL_ATTACH_AS_ZIP : "1" で常にZIP化して1通で送る（既定 "0"）
#   MAX_MAIL_SIZE_MB   : 添付合計の上限MB（既定 20）。超えたらZIP化して1通
#   MAIL_SLACK_NOTIFY  : "0" でSlack同報を抑止（既定 "1"）
#
# Slack（任意）
#   SLACK_BOT_TOKEN   : Bot User OAuth Token (xoxb-...)
#   SLACK_CHANNEL_ID  : 投稿先チャンネルID
#
# Weathercaster からの付加情報（任意）
#   WX_ATTACH_COUNT   : 添付ファイル数（int文字列）
#   WX_ERROR_COUNT    : 変換等のエラー件数（int文字列）
# =============================================================================
import os
import smtplib
import socket
import tempfile
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

def _bytes_to_mb(n: int) -> float:
    return n / (1024.0 * 1024.0)

def _build_message(
    mail_from: str,
    to_addrs: Iterable[str],
    subject: str,
    body: str,
    is_html: bool,
    cc_addrs: Iterable[str],
    attachments: List[Tuple[str, bytes, str]],
) -> MIMEMULTIPART:
    msg = MIMEMultipart()
    disp = Address(display_name="", username=mail_from.split("@")[0], domain=mail_from.split("@")[1])
    msg["From"] = formataddr((str(disp), mail_from))
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

    for name, blob, ctype in attachments:
        part = MIMEApplication(blob, Name=name)
        part.add_header("Content-Disposition", "attachment", filename=name)
        if ctype:
            part.add_header("Content-Type", ctype)
        msg.attach(part)
    return msg  # type: ignore[name-defined]

def _connect_and_send(
    host: str,
    port: int,
    user: str,
    password: str,
    envelope_from: str,
    recipients: List[str],
    msg: MIMEMULTIPART,
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
# Slack 同報（一元化・所望フォーマットで1件）
# -----------------------------------------------------------------------------
def _notify_slack(subject: str, recipients: List[str], success: bool,
                  files: Optional[List[str]] = None, error: Optional[str] = None):
    """Slackへ1件だけ投稿。Weathercaster 側で WX_* を渡せば件数を正確表示。"""
    if os.environ.get("MAIL_SLACK_NOTIFY", "1") != "1":
        return

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not (token and channel):
        return

    # 件数（環境変数優先。無ければ推定／失敗時は1）
    try:
        attach_count = int((os.environ.get("WX_ATTACH_COUNT") or "").strip())
    except Exception:
        attach_count = len(files) if files else 0

    try:
        error_count = int((os.environ.get("WX_ERROR_COUNT") or "").strip())
    except Exception:
        error_count = 0 if success else 1

    # 日本語エイリアスの絵文字（ご希望どおり）
    lines = [
        ":チェックマーク_緑: Mail sent" if success else ":x: Mail failed",
        f"Subject: {subject}",
        f"To: {', '.join(recipients)}",
        f":地球_アジア: 添付: {attach_count}件 / エラー: {error_count}件",
    ]
    if (not success) and error:
        lines.append(f"```{(error or '')[:900]}```")

    text = "\n".join(lines)

    # slack_utils があれば使用、無ければ直接API
    try:
        from module.utils.slack_utils import send_slack_text  # type: ignore
        send_slack_text(channel=channel, message=text)
        return
    except Exception:
        pass

    try:
        import json, urllib.request
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
# 公開関数（1通でまとめて送る）
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
    メール送信（常に“1通でまとめる”）。成功時 Message-ID 風の識別子を返す。
    - 複数ファイル添付OK
    - 合計サイズ > MAX_MAIL_SIZE_MB or MAIL_ATTACH_AS_ZIP=1 の場合はZIP化して1通
    """
    #
