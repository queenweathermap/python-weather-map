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
) -> MIMEMultipart:
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
# Slack 同報（一元化・所望フォーマットで1件）
# -----------------------------------------------------------------------------
def notify_slack(
    subject: str,
    recipients: List[str],
    success: bool,
    files: Optional[List[str]] = None,
    error: Optional[str] = None,
    upload_paths: Optional[List[str]] = None,  # 将来のファイル送信に備えて追加
):
    """
    Slackへ1件だけ投稿。Weathercaster 側で WX_* を渡せば件数を正確表示。
    - upload_paths: 将来的にSlackへ実ファイルを添付したいときに使用予定。
    """
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

    # 通知本文
    lines = [
        "✉️ Mail sent" if success else "❌ Mail failed",
        f"Subject: {subject}",
        f"To: {', '.join(recipients) if recipients else '(none)'}",
        f"📎 添付: {attach_count}件 / エラー: {error_count}件",
    ]
    if (not success) and error:
        lines.append(f"```{(error or '')[:900]}```")

    text = "\n".join(lines)

    # --- まずはテキスト通知のみ ---
    try:
        from module.utils.slack_utils import send_slack_text
        send_slack_text(channel=channel, message=text)
    except Exception as e:
        print(f"[WARN] Slackテキスト送信に失敗: {e}")

    # --- 将来のファイル送信フック ---
    if upload_paths:
        print(f"[INFO] upload_paths={upload_paths} が指定されましたが、現時点では未対応です。")
        # TODO: 将来的に slack_utils.upload_files_slack を呼び出す予定



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
    # --- env 既定 ---
    mail_from = mail_from or os.environ.get("FROM_EMAIL", "")
    to_addrs = to_addrs or os.environ.get("TO_EMAIL", "")
    smtp_host = smtp_host or os.environ.get("SMTP_SERVER", "")
    smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", "587"))
    smtp_user = smtp_user or os.environ.get("SMTP_USERNAME", "")
    smtp_pass = smtp_password or os.environ.get("SMTP_PASSWORD", "")
    debug = os.environ.get("MAIL_DEBUG", "0") == "1"
    subject_prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "").strip()
    if subject_prefix and not subject.startswith(subject_prefix):
        subject = f"{subject_prefix} {subject}"

    # --- 必須チェック ---
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

    # --- 添付読み込み ---
    src_files: List[str] = []
    blobs: List[Tuple[str, bytes, str]] = list(attachment_blobs or [])

    if attachment_paths:
        for p in attachment_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"添付が見つかりません: {p}")
            src_files.append(p)

    # 合計サイズでZIP判定
    total_bytes = sum(os.path.getsize(p) for p in src_files) if src_files else 0
    max_mb = float(os.environ.get("MAX_MAIL_SIZE_MB", "20"))
    force_zip = os.environ.get("MAIL_ATTACH_AS_ZIP", "0") == "1"
    need_zip = force_zip or _bytes_to_mb(total_bytes) > max_mb

    temp_zip_path = None
    if src_files and not need_zip:
        # そのまま複数添付（バイナリ化）
        for p in src_files:
            with open(p, "rb") as f:
                blobs.append((os.path.basename(p), f.read(), "application/octet-stream"))
    elif src_files:
        # ZIPにまとめて1通
        from module.utils.zip_utils import zip_files
        fd, tmp_path = tempfile.mkstemp(prefix="mail_attach_", suffix=".zip")
        os.close(fd)
        zip_files(src_files, tmp_path)
        temp_zip_path = tmp_path
        with open(tmp_path, "rb") as f:
            blobs.append((os.path.basename(tmp_path), f.read(), "application/zip"))
        if "[ZIP]" not in subject:
            subject = f"{subject} [ZIP]"

    # --- メッセージ構築 ---
    msg = _build_message(
        mail_from=mail_from,
        to_addrs=to_list,
        subject=subject,
        body=body,
        is_html=is_html,
        cc_addrs=cc_list,
        attachments=blobs,
    )

    envelope_from = smtp_user  # 認証ユーザーをEnvelope-Fromに

    # 注意喚起（ドメイン不一致）
    from_domain = mail_from.split("@")[-1].lower()
    user_domain = smtp_user.split("@")[-1].lower()
    if from_domain != user_domain:
        print(f"[WARN] From({from_domain}) と SMTP_USERNAME({user_domain}) のドメインが不一致です。拒否される可能性があります。")

    # --- 送信（最大2回: 587→465） ---
    ports = [smtp_port] if smtp_port in (465, 587) else [587, 465]
    last_err = None
    try:
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
                notify_slack(subject=subject, recipients=recipients, success=True, files=src_files or [blobs[0][0]])
                return mid
            except smtplib.SMTPResponseException as e:
                err = f"SMTP {e.smtp_code} {e.smtp_error}"
                print(f"[ERR] {err}")
                last_err = err
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                print(f"[ERR] SMTP送信失敗（port={port}）: {err}")
                last_err = err
        notify_slack(subject=subject, recipients=recipients, success=False, files=src_files, error=str(last_err) if last_err else None)
        raise RuntimeError(f"メール送信に失敗しました（{attempt}回試行）: {last_err}")
    finally:
        if temp_zip_path and os.path.exists(temp_zip_path):
            try: os.remove(temp_zip_path)
            except Exception: pass
