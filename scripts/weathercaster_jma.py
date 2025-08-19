# -*- coding: utf-8 -*-
# =============================================================================
# scripts/weathercaster_jma.py
# 気象庁 Weathercaster（会員ページ）PDFを保存せずにDL→JPG化
# 出力は /tmp に展開 → ZIP化し、優先して GCS に保存。
# MAIL_TO があればメール送信（既定は ZIP 添付、MAIL_AS_ZIP="0" ならJPGを複数添付）。
# Slack 通知は環境変数 SLACK_* があれば送信。
# =============================================================================

import os
import io
import shutil
from datetime import datetime
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes

from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"
PDF_FILES = [
    "COMP12.pdf","COMP36.pdf","COMP72.pdf",
    "FXXN519.pdf","FZCX50.pdf","FXJP854.pdf","FEFE19.pdf",
    "TKAISETU.pdf","SKAISETU.pdf",
    "AUPA20.pdf","AUPN30.pdf","AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "")
PASS = os.environ.get("WEATHERCASTER_PASS", "")

# Cloud Run 書込先
DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

# 変換/送付オプション
ATTACH_ALL_PAGES = os.environ.get("MAIL_ATTACH_ALL_PAGES", "0") == "1"  # JPG添付時：全ページ
MAIL_AS_ZIP = os.environ.get("MAIL_AS_ZIP", "1") == "1"                  # 既定はZIP添付
JPEG_DPI = 200
JPEG_QUALITY = 85
# -----------------------

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def upload_to_gcs(bucket_name: str, blob_name: str, data: bytes) -> str:
    """GCS にアップロードして gs:// パスを返す"""
    from google.cloud import storage
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(data)
    return f"gs://{bucket_name}/{blob_name}"


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


def build_outputs(today: str) -> Tuple[List[Attachment], List[str]]:
    """全PDFをDL→JPG化。OUTPUT_DIR にファイルを書き出し、メール添付用配列も返す"""
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
        if name == "SKAISETU.pdf":
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=True, simple_index=True)
        else:
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=False, simple_index=False)

        if not imgs:
            errors.append(f"{name}: conversion produced no images")
            continue

        # OUTPUT_DIR に実ファイルも保存（ZIP化用）
        for fname, blob, _ in imgs:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)
        emails.extend(imgs)

    return emails, errors


def main():
    slack_ch = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    mail_to = os.environ.get("MAIL_TO", os.environ.get("TO_EMAIL", "")).strip()  # 互換

    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "[Weathercaster]").strip()
    subject = f"{prefix} 天気図 JPG {today}"

    gcs_uri = None
    msg_id = None

    try:
        emails, errors = build_outputs(today)

        # ZIP 作成
        zip_bytes = to_zip_bytes_from_dir(OUTPUT_DIR)
        zip_name = f"weathercaster_jma_{today}.zip"

        # 優先: GCS へ保存
        if bucket:
            gcs_uri = upload_to_gcs(bucket, f"weathercaster-jma/{today}/{zip_name}", zip_bytes)
            print(f"[OK] Uploaded to {gcs_uri}")

        # メール送信（任意）
        if mail_to:
            if MAIL_AS_ZIP:
                msg_id = send_mail(
                    to_addrs=mail_to,
                    subject=subject,
                    body=("気象庁Weathercasterの天気図をJPG化しZIP添付します（保存なし運用）。\n"
                          + ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")),
                    attachment_blobs=[(zip_name, zip_bytes, "application/zip")],
                )
            else:
                msg_id = send_mail(
                    to_addrs=mail_to,
                    subject=subject,
                    body=("気象庁Weathercasterの天気図をJPG化して添付します（保存なし運用）。\n"
                          + ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")),
                    attachment_blobs=emails,
                )
            print(f"[OK] Mail sent. Message-ID: {msg_id}")

        # Slack 通知（任意）
        if slack_ch:
            try:
                files_n = len(os.listdir(OUTPUT_DIR))
                note = f":white_check_mark: JMA完了 {today}\nfiles: {files_n}, errors: {len(errors)}"
                if gcs_uri: note += f"\nGCS: {gcs_uri}"
                if msg_id:  note += f"\nMessage-ID: {msg_id}"
                send_slack_text(channel=slack_ch, message=note)
            except Exception:
                pass

    except Exception as e:
        if slack_ch:
            try:
                send_slack_text(slack_ch, f":x: JMA失敗 {today}\n{e}")
            except Exception:
                pass
        print(f"[ERROR] {e}")
        raise
    finally:
        try:
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            shutil.rmtree(DATA_DIR, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
