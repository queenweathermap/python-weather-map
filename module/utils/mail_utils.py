# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/mail_utils.py
# =============================================================================
# 目的  : SMTP を用いたメール送信ユーティリティ（添付・HTML・CC/BCC・BytesIO対応）
# 方針  : 依存は標準ライブラリ中心。設定は .env / 環境変数 / 引数の順で上書き。
# 想定  : GitHub Actions 等の一時環境で「保存せずZip添付→送信」に最適化。
# 仕様  :
#   - 平文/HTML 本文、複数宛先、CC/BCC、Reply-To、件名接頭辞に対応
#   - 添付は「ファイルパス」または「(filename, bytes, mimetype)」のどちらも可
#   - STARTTLS(587) / SMTPS(465) の両方に対応（ポートで自動判定）
#   - タイムアウト、再試行（軽め）に対応
#   - 返り値として Message-ID を返す（運用ログの相関に便利）
#
# 必要パッケージ:
#   - python-dotenv（任意）: .env の読み込みに使用。無い場合はスキップ。
#
# 推奨環境変数（どれも未指定なら引数で渡してください）:
#   SMTP_HOST / SMTP_SERVER / MAIL_SMTP_SERVER   : SMTPホスト名
#   SMTP_PORT / MAIL_PORT                        : ポート番号 (例: 587 or 465)
#   SMTP_USER / MAIL_USER                        : 認証ユーザ
#   SMTP_PASS / MAIL_PASS                        : 認証パスワード/アプリパス
#   MAIL_FROM                                    : 送信者アドレス
#   MAIL_SUBJECT_PREFIX                          : 件名の接頭辞（例: "[Akita]"）
#   MAIL_TIMEOUT_SEC                             : 接続・送信のタイムアウト秒（整数）
#
# 使い方（最小例）:
#   from module.utils.mail_utils import send_mail
#   send_mail(
#       to_addrs="recipient@example.com",
#       subject="テスト",
#       body="本文だけの簡易送信です。"
#   )
#
# 添付の使い方:
#   # パスで添付
#   send_mail(..., attachment_paths=["/tmp/result.zip"])
#
#   # メモリ上のバイト列で添付（MIME を明示）
#   send_mail(
#       ...,
#       attachment_blobs=[("result.zip", zip_bytes, "application/zip")]
#   )
#
# ライセンス: MIT（必要に応じて変更してください）
# =============================================================================

from __future__ import annotations

import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple, Union

try:
    # 任意。無ければ何もしない
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from email.message import EmailMessage
from email.utils import make_msgid, formatdate


# -----------------------------------------------------------------------------
# 型定義
# -----------------------------------------------------------------------------
AttachmentBlob = Tuple[str, bytes, str]  # (filename, content_bytes, mimetype)


# -----------------------------------------------------------------------------
# 内部ユーティリティ
# -----------------------------------------------------------------------------
def _env(*keys: str, default: Optional[str] = None) -> Optional[str]:
    """
    環境変数を複数キーで探索して最初に見つかった値を返す。
    例: _env("SMTP_HOST", "SMTP_SERVER", "MAIL_SMTP_SERVER")
    """
    for k in keys:
        v = os.environ.get(k)
        if v not in (None, ""):
            return v
    return default


def _ensure_list(x: Union[str, Sequence[str], None]) -> List[str]:
    """宛先指定の表現ゆれに対応（str / list[str] / None ⇒ list[str]）"""
    if x is None:
        return []
    if isinstance(x, str):
        # カンマ区切りにも軽く対応
        return [a.strip() for a in x.split(",") if a.strip()]
    return [str(a).strip() for a in x if str(a).strip()]


def _guess_mime(filename: str) -> Tuple[str, str]:
    """拡張子から簡易MIME推定（最低限）。指定が無い Blob には application/octet-stream を返す。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application", "pdf"
    if lower.endswith(".zip"):
        return "application", "zip"
    if lower.endswith(".png"):
        return "image", "png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image", "jpeg"
    if lower.endswith(".txt"):
        return "text", "plain"
    return "application", "octet-stream"


# -----------------------------------------------------------------------------
# 設定データクラス
# -----------------------------------------------------------------------------
@dataclass
class SMTPConfig:
    host: str
    port: int = 587
    user: Optional[str] = None
    password: Optional[str] = None
    mail_from: Optional[str] = None
    subject_prefix: Optional[str] = None
    timeout_sec: int = 60

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        host = _env("SMTP_HOST", "SMTP_SERVER", "MAIL_SMTP_SERVER", default="")
        port_str = _env("SMTP_PORT", "MAIL_PORT", default="587")
        user = _env("SMTP_USER", "MAIL_USER")
        password = _env("SMTP_PASS", "MAIL_PASS")
        mail_from = _env("MAIL_FROM")
        prefix = _env("MAIL_SUBJECT_PREFIX")
        timeout_str = _env("MAIL_TIMEOUT_SEC", default="60")

        try:
            port = int(port_str)
        except Exception:
            port = 587

        try:
            timeout = int(timeout_str)
        except Exception:
            timeout = 60

        return cls(
            host=host,
            port=port,
            user=user,
            password=password,
            mail_from=mail_from,
            subject_prefix=prefix,
            timeout_sec=timeout,
        )


# -----------------------------------------------------------------------------
# メイン関数
# -----------------------------------------------------------------------------
def send_mail(
    to_addrs: Union[str, Sequence[str]],
    subject: str,
    body: str = "",
    *,
    # 本文の別形態
    html_body: Optional[str] = None,
    # 添付（パス or バイト列）
    attachment_paths: Optional[Iterable[str]] = None,
    attachment_blobs: Optional[Iterable[AttachmentBlob]] = None,
    # ヘッダ系
    cc_addrs: Optional[Union[str, Sequence[str]]] = None,
    bcc_addrs: Optional[Union[str, Sequence[str]]] = None,
    reply_to: Optional[Union[str, Sequence[str]]] = None,
    # 設定（未指定は環境変数から）
    mail_from: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    subject_prefix: Optional[str] = None,
    timeout_sec: Optional[int] = None,
    # 送信挙動
    retries: int = 1,  # 失敗時の追加試行回数（合計=1+retries）
) -> str:
    """
    SMTPメール送信（HTML/添付/CC/BCC対応）

    Returns:
        str: 送信に使用した Message-ID（ログ相関用）

    Raises:
        Exception: 接続・認証・送信いずれかの失敗時
    """
    # 1) 設定の解決（引数 > 環境変数）
    env_cfg = SMTPConfig.from_env()
    cfg = SMTPConfig(
        host=smtp_host or env_cfg.host,
        port=int(smtp_port or env_cfg.port),
        user=smtp_user or env_cfg.user,
        password=smtp_password or env_cfg.password,
        mail_from=mail_from or env_cfg.mail_from,
        subject_prefix=subject_prefix or env_cfg.subject_prefix,
        timeout_sec=int(timeout_sec or env_cfg.timeout_sec),
    )
    if not cfg.host:
        raise ValueError("SMTP ホストが未設定です（smtp_host または環境変数 SMTP_HOST 等）")

    # 2) 宛先の整形
    to_list = _ensure_list(to_addrs)
    cc_list = _ensure_list(cc_addrs)
    bcc_list = _ensure_list(bcc_addrs)
    if not to_list and not cc_list and not bcc_list:
        raise ValueError("宛先が空です（to/cc/bcc のいずれかは必須）")

    # 3) メッセージ構築
    msg = EmailMessage()
    msg["From"] = cfg.mail_from or (cfg.user or "no-reply@example.com")
    msg["To"] = ", ".join(to_list) if to_list else ""
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if reply_to:
        msg["Reply-To"] = ", ".join(_ensure_list(reply_to))
    msg["Date"] = formatdate(localtime=True)

    if cfg.subject_prefix:
        msg["Subject"] = f"{cfg.subject_prefix} {subject}".strip()
    else:
        msg["Subject"] = subject

    # 本文（text/plain + 任意で text/html の alternative）
    if html_body is not None:
        msg.set_content(body or "")
        msg.add_alternative(html_body, subtype="html")
    else:
        # 平文のみ
        msg.set_content(body or "")

    # 4) 添付（ファイルパス）
    if attachment_paths:
        for p in attachment_paths:
            try:
                with open(p, "rb") as f:
                    data = f.read()
                maintype, subtype = _guess_mime(p)
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(p),
                )
            except FileNotFoundError:
                # 見つからない場合は明示的にエラーにする方が運用しやすい
                raise FileNotFoundError(f"添付ファイルが見つかりません: {p}")

    # 5) 添付（メモリ上のバイト列）
    if attachment_blobs:
        for filename, data, mimetype in attachment_blobs:
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("attachment_blobs の data は bytes で指定してください")
            if "/" in mimetype:
                maintype, subtype = mimetype.split("/", 1)
            else:
                maintype, subtype = _guess_mime(filename)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    # Message-ID を先に生成しておく（返り値として利用）
    message_id = make_msgid()
    msg["Message-ID"] = message_id

    # 6) 送信（ポートから STARTTLS/SMTPS を自動選択）
    all_recipients = list({*to_list, *cc_list, *bcc_list})
    attempt = 0
    last_err: Optional[BaseException] = None

    while attempt <= max(0, int(retries)):
        try:
            if cfg.port == 465:
                # SMTPS（SSL 即時）
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout_sec, context=context) as server:
                    if cfg.user:
                        server.login(cfg.user, cfg.password or "")
                    server.send_message(msg, to_addrs=all_recipients)
            else:
                # SMTP + STARTTLS（よく使う 587）
                with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_sec) as server:
                    server.ehlo()
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()
                    if cfg.user:
                        server.login(cfg.user, cfg.password or "")
                    server.send_message(msg, to_addrs=all_recipients)

            # 成功
            return message_id

        except Exception as e:
            last_err = e
            attempt += 1
            if attempt > retries:
                break
            # 短い指数バックオフ（1s, 2s, 4s … 最大8s程度）
            time.sleep(min(2 ** attempt, 8))

    # ここに来たら失敗
    raise RuntimeError(f"メール送信に失敗しました（{attempt}回試行）: {last_err}")


# -----------------------------------------------------------------------------
# 互換ラッパ（従来の引数名に合わせたい時用）
# -----------------------------------------------------------------------------
def send_mail_with_attachments(
    subject: str,
    body: str,
    attachments: Iterable[AttachmentBlob],
    to_addrs: Union[str, Sequence[str], None] = None,
    **kwargs,
) -> str:
    """
    互換 API：以前提案した (filename, bytes, mimetype) 形式のみに特化した送信。
    """
    to_addrs = to_addrs or os.environ.get("MAIL_TO", "")
    return send_mail(
        to_addrs=to_addrs,
        subject=subject,
        body=body,
        attachment_blobs=list(attachments),
        **kwargs,
    )
