# -*- coding: utf-8 -*-
# =============================================================================
# scripts/weathercaster_jma.py
# 気象庁 Weathercaster（会員ページ）PDFを保存せずにDL→JPG化
# - 出力は /tmp に展開
# - メール送信（JPGを複数添付：ZIPにしない）
# - Slack通知は mail_utils.py に集約（slack_modeで制御）
#
# 必須ENV:
#   WEATHERCASTER_USER, WEATHERCASTER_PASS
#
# Mail ENV（mail_utils.py準拠）:
#   FROM_EMAIL, TO_EMAIL(or MAIL_TO), SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
#   MAIL_SUBJECT_PREFIX
#   MAIL_ATTACH_AS_ZIP="0" 推奨（ZIP禁止）
#   MAX_MAIL_SIZE_MB="100" 推奨（サイズ超でZIPにならないように）
#
# Slack ENV（mail_utils.py準拠）:
#   SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
#   MAIL_SLACK_NOTIFY="1"
# =============================================================================

import io
import os
import shutil
from datetime import datetime
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes

from module.utils.mail_utils import send_mail

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"
PDF_FILES = [
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXXN519.pdf", "FZCX50.pdf", "FXJP854.pdf", "FEFE19.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf",
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "")
PASS = os.environ.get("WEATHERCASTER_PASS", "")

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

# 変換/送付オプション
ATTACH_ALL_PAGES = os.environ.get("MAIL_ATTACH_ALL_PAGES", "0") == "1"  # JPG添付時：全ページ
JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))
# -----------------------

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def fetch_pdf_content(name: str) -> Optional[bytes]:
    """Basic認証でPDFを取得。失敗時 None"""
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


def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
    simple_index: bool = False,
) -> List[Attachment]:
    """PDFをJPGへ。返り値は (filename, blob, mimetype) の配列"""
    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not images:
        return []

    atts: List[Attachment] = []

    # 全ページ添付（SKAISETUなど）
    if ATTACH_ALL_PAGES or force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            fname = f"{base_filename}_{idx}.jpg" if simple_index else f"{base_filename}_p{idx:02d}.jpg"
            atts.append((fname, buf.getvalue(), "image/jpeg"))
        return atts

    # 1ページ目だけ添付
    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    atts.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))
    return atts


def build_outputs(today: str) -> Tuple[List[Attachment], List[str]]:
    """全PDFをDL→JPG化。OUTPUT_DIR に書き出し、メール添付用配列も返す"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    emails: List[Attachment] = []
    errors: List[str] = []

    if not USER or not PASS:
        errors.append("WEATHERCASTER_USER / PASS が未設定です")

    for name in PDF_FILES:
        pdf = fetch_pdf_content(name)
        if pdf is None:
            errors.append(f"{name}: download failed")
            continue

        base = f"{today}_{name.replace('.pdf', '')}"

        # SKAISETU は全ページ（簡易連番）／それ以外は1枚
        if name == "SKAISETU.pdf":
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=True, simple_index=True)
        else:
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=False, simple_index=False)

        if not imgs:
            errors.append(f"{name}: conversion produced no images")
            continue

        # 実ファイルとしても保存（デバッグ用・将来のZIP化などに備える）
        for fname, blob, _ in imgs:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)

        emails.extend(imgs)

    return emails, errors


def main():
    # 宛先（互換）
    mail_to = os.environ.get("MAIL_TO", os.environ.get("TO_EMAIL", "")).strip()

    # Slack通知モード（mail_utilsに渡す）
    #  "off" / "error_only" / "success"
    slack_mode = os.environ.get("SLACK_MODE", "success").strip()

    # 件名
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "[JMA]").strip()
    subject = f"{prefix} 天気図 JPG {today}"

    try:
        emails, errors = build_outputs(today)

        # 件数を mail_utils 側に伝える（Slack表示の精度UP）
        os.environ["WX_ATTACH_COUNT"] = str(len(emails))
        os.environ["WX_ERROR_COUNT"] = str(len(errors))

        # メール送信（ZIPにしない＝個別添付）
        if mail_to:
            body = (
                "気象庁Weathercasterの天気図をJPG化して添付します（保存なし運用）。\n"
                + ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")
            )

            msg_id = send_mail(
                to_addrs=mail_to,
                subject=subject,
                body=body,
                attachment_blobs=emails,      # ← 個別添付（13枚）
                slack_mode=slack_mode,        # ← Slackは mail_utils に集約
            )
            print(f"[OK] Mail sent. Message-ID: {msg_id}")
        else:
            print("[WARN] MAIL_TO/TO_EMAIL が未設定のためメール送信をスキップしました。")

    finally:
        # 後片付け
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
