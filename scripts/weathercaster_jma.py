# -*- coding: utf-8 -*-
# =============================================================================
# 気象庁 Weathercaster（会員ページ）から指定PDFを保存せずにDL→JPG化→メール添付
# 既定は各PDFの「1ページ目のみ」JPG添付。
# MAIL_ATTACH_ALL_PAGES="1" で全ページJPG添付。
# SKAISETU.pdf は常に2ページ添付（_1 / _2）。
# Slack 通知はこのスクリプト内で送信（環境変数 SLACK_* があれば）。
# =============================================================================

import os
import io
from datetime import datetime
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes

from module.utils.mail_utils import send_mail
try:
    from module.utils.slack_utils import send_slack_text  # 既存ユーティリティ
except Exception:
    send_slack_text = None  # Slack無しでも動くように

# ---- 設定 -------------------------------------------------------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

# 配信対象PDF（必要に応じて編集）
PDF_FILES = [
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXXN519.pdf", "FZCX50.pdf", "FXJP854.pdf", "FEFE19.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf",
    # 追加分
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "")
PASS = os.environ.get("WEATHERCASTER_PASS", "")
MAIL_TO = os.environ.get("TO_EMAIL", "")

ATTACH_ALL_PAGES = os.environ.get("MAIL_ATTACH_ALL_PAGES", "0") == "1"
JPEG_DPI = 200
JPEG_QUALITY = 85
# ---------------------------------------------------------------

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def _slack_notify_ok(subject: str, files: List[Attachment], errors: List[str]) -> None:
    channel = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    if not channel or send_slack_text is None:
        return
    msg = f":white_check_mark: {subject}\nfiles: {len(files)}  errors: {len(errors)}"
    if errors:
        msg += "\n" + "\n".join(f"- {e}" for e in errors[:10])
    try:
        send_slack_text(channel=channel, message=msg)
    except Exception:
        pass


def _slack_notify_ng(subject: str, error: str) -> None:
    channel = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    if not channel or send_slack_text is None:
        return
    try:
        send_slack_text(channel=channel, message=f":x: {subject}\n{error}")
    except Exception:
        pass


def fetch_pdf_content(name: str) -> Optional[bytes]:
    """Basic認証でPDFを取得し、bytesを返す。失敗時は None。"""
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        if r.status_code == 200:
            print(f"[OK] {name} downloaded")
            return r.content
        print(f"[NG] {name} HTTP {r.status_code}")
        return None
    except Exception as e:
        print(f"[ERR] {name} {e}")
        return None


def pdf_bytes_to_jpg_attachments(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
    simple_index: bool = False,
) -> List[Attachment]:
    """
    PDFバイト列をJPGに変換し、(filename, blob, mimetype) のリストで返す。
      - 既定は1ページ目のみ。ATTACH_ALL_PAGES または force_all=True で全ページ。
      - simple_index=True の場合、連番は _1, _2 ... とする（SKAISETU向け）。
        それ以外は _p01, _p02 のようにゼロ埋め。
    """
    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not images:
        return []

    atts: List[Attachment] = []
    if ATTACH_ALL_PAGES or force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            fname = f"{base_filename}_{idx}.jpg" if simple_index else f"{base_filename}_p{idx:02d}.jpg"
            atts.append((fname, buf.getvalue(), "image/jpeg"))
    else:
        buf = io.BytesIO()
        images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        atts.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))

    return atts


def fetch_and_convert_all(today_str: str) -> Tuple[List[Attachment], List[str]]:
    """対象PDFを順次DL→JPG化して添付配列を構築。"""
    all_attachments: List[Attachment] = []
    errors: List[str] = []

    if not USER or not PASS:
        errors.append("WEATHERCASTER_USER / PASS が未設定です")

    for name in PDF_FILES:
        pdf_bytes = fetch_pdf_content(name)
        if pdf_bytes is None:
            errors.append(f"{name}: download failed")
            continue

        base = f"{today_str}_{name.replace('.pdf', '')}"
        if name == "SKAISETU.pdf":
            jpgs = pdf_bytes_to_jpg_attachments(pdf_bytes, base, force_all=True, simple_index=True)
        else:
            jpgs = pdf_bytes_to_jpg_attachments(pdf_bytes, base, force_all=False, simple_index=False)

        if jpgs:
            all_attachments.extend(jpgs)
        else:
            errors.append(f"{name}: conversion produced no images")

    return all_attachments, errors


def main():
    today = datetime.now().strftime("%Y%m%d")
    prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "").strip()
    subject = f"{prefix} Weathercaster 天気図 JPG {today}".strip()

    try:
        # 1) DL→JPG変換（保存なし）
        attachments, errors = fetch_and_convert_all(today)

        # 2) メール送信（複数JPGをそのまま添付）
        mode = "全ページ" if ATTACH_ALL_PAGES else "1ページ目のみ（SKAISETUは常に2ページ）"
        detail = ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")
        body = (
            f"気象庁Weathercasterの天気図PDFをJPGに変換して添付します（{mode}・保存なし運用）。\n"
            f"{detail}"
        )

        msg_id = send_mail(
            to_addrs=MAIL_TO,
            subject=subject,
            body=body,
            attachment_blobs=attachments,
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id} / files: {len(attachments)} / errors: {len(errors)}")

        # 3) Slack通知
        _slack_notify_ok(subject, attachments, errors)

    except Exception as e:
        _slack_notify_ng(f"{subject}（失敗）", str(e))
        print(f"[ERROR] {e}")
        raise


if __name__ == "__main__":
    main()
