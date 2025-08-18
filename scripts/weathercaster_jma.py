# -*- coding: utf-8 -*-
# =============================================================================
# scripts/weathercaster_jma.py
# -----------------------------------------------------------------------------
# 気象庁 Weathercaster（会員ページ）から指定PDFを**保存せず**一括DL
# PDFはJPGへ変換し、メールに直接添付（ZIPなし）。
#   - 既定: 各PDFの「1ページ目のみ」JPG添付（軽量運用）
#   - 環境変数 MAIL_ATTACH_ALL_PAGES="1" で全ページJPG添付
#   - ただし SKAISETU.pdf は常に2ページ分を添付（_1 / _2）
# Drive 永続保存は一切しない。Slack 通知は任意。
# =============================================================================

import os
from datetime import datetime
import io
import requests

from pdf2image import convert_from_bytes
from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text  # 任意

# ---- 設定 -------------------------------------------------------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

# 配信対象PDF（必要に応じて編集）
PDF_FILES = [
    "COMP12.pdf",
    "COMP36.pdf",
    "COMP72.pdf",
    "FXXN519.pdf",
    "FZCX50.pdf",
    "FXJP854.pdf",
    "FEFE19.pdf",
    "TKAISETU.pdf",
    "SKAISETU.pdf",   # ← これだけ常に2ページ（後述の処理で制御）
    # 追加分
    "AUPA20.pdf",
    "AUPN30.pdf",
    "AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER")
PASS = os.environ.get("WEATHERCASTER_PASS")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")  # 任意
MAIL_TO = os.environ.get("TO_EMAIL", "")

# 変換設定
ATTACH_ALL_PAGES = os.environ.get("MAIL_ATTACH_ALL_PAGES", "0") == "1"
JPEG_DPI = 200        # 画質/サイズのバランス
JPEG_QUALITY = 85     # 画質（80-90推奨）
# ---------------------------------------------------------------


def fetch_pdf_content(name: str) -> bytes | None:
    """Basic認証でPDFを取得し、bytesを返す。失敗時はNone。"""
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        if r.status_code == 200:
            print(f"[OK] {name} downloaded")
            return r.content
        else:
            print(f"[NG] {name} HTTP {r.status_code}")
            return None
    except Exception as e:
        print(f"[ERR] {name} {e}")
        return None


def pdf_bytes_to_jpg_attachments(pdf_bytes: bytes, base_filename: str, force_all: bool = False, simple_index: bool = False):
    """
    PDFバイト列をJPGに変換し、(filename, blob, mimetype) のリストで返す。
      - 既定は1ページ目のみ。ATTACH_ALL_PAGES または force_all=True で全ページ。
      - simple_index=True の場合、連番は _1, _2 ... とする（SKAISETU向け）。
        それ以外は _p01, _p02 のようにゼロ埋め。
    """
    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    attachments = []
    if not images:
        return attachments

    if ATTACH_ALL_PAGES or force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            if simple_index:
                fname = f"{base_filename}_{idx}.jpg"
            else:
                fname = f"{base_filename}_p{idx:02d}.jpg"
            attachments.append((fname, buf.getvalue(), "image/jpeg"))
    else:
        buf = io.BytesIO()
        images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        fname = f"{base_filename}.jpg"
        attachments.append((fname, buf.getvalue(), "image/jpeg"))

    return attachments


def fetch_and_convert_all(today_str: str):
    """
    対象PDFを順次DL→JPG化して添付配列を構築。
    returns: (attachments, errors)
      attachments: [(filename, blob, mimetype), ...]
      errors: [error_message, ...]
    """
    all_attachments = []
    errors = []

    for name in PDF_FILES:
        pdf_bytes = fetch_pdf_content(name)
        if pdf_bytes is None:
            errors.append(f"{name}: download failed")
            continue

        base = f"{today_str}_{name.replace('.pdf', '')}"

        if name == "SKAISETU.pdf":
            # 常に2ページ分を _1 / _2 で命名
            jpgs = pdf_bytes_to_jpg_attachments(
                pdf_bytes,
                base,
                force_all=True,
                simple_index=True,
            )
        else:
            # 通常は1ページ目のみ（必要なら環境変数で全ページに切替可）
            jpgs = pdf_bytes_to_jpg_attachments(
                pdf_bytes,
                base,
                force_all=False,
                simple_index=False,
            )

        if jpgs:
            all_attachments.extend(jpgs)
        else:
            errors.append(f"{name}: conversion produced no images")

    return all_attachments, errors


def main():
    today = datetime.now().strftime("%Y%m%d")

    try:
        # 1) DL→JPG変換（メモリ）
        attachments, errors = fetch_and_convert_all(today)

        # 2) メール送信（複数JPGをそのまま添付）
        subject = f"Weathercaster 天気図 JPG {today}"
        mode = "全ページ" if ATTACH_ALL_PAGES else "1ページ目のみ（SKAISETUは常に2ページ）"
        body = (
            f"気象庁Weathercasterの天気図PDFをJPGに変換して添付します（{mode}・保存なし運用）。\n"
            + ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")
        )

        msg_id = send_mail(
            to_addrs=MAIL_TO,
            subject=subject,
            body=body,
            attachment_blobs=attachments,  # [(filename, blob, mimetype), ...]
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id} / files: {len(attachments)} / errors: {len(errors)}")

        # 3) 任意: Slack 通知（結果サマリ）
        if SLACK_CHANNEL_ID:
            summary = f"添付: {len(attachments)}件 / エラー: {len(errors)}件"
            if errors:
                summary += "\n・" + "\n・".join(errors)
            send_slack_text(
                channel=SLACK_CHANNEL_ID,
                message=f":earth_asia: {today} Weathercaster JPG メール送信\n{summary}",
            )

    except Exception as e:
        if SLACK_CHANNEL_ID:
            send_slack_text(channel=SLACK_CHANNEL_ID, message=f":x: Weathercaster 送信失敗: {e}")
        raise


if __name__ == "__main__":
    main()
