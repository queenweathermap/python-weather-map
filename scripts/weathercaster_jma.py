# -*- coding: utf-8 -*-
# =============================================================================
# scripts/daily_weathercaster_notify.py
# -----------------------------------------------------------------------------
# 気象庁 Weathercaster（会員ページ）から指定PDFを**保存せず**一括DLし、
# メモリ上で ZIP 化してメール添付で配信するバッチ。
#
# 以前の JPG 変換/マージ画像生成は行わず、PDFのまま ZIP にまとめるため高速・軽量。
# Drive 永続保存は一切しない。Slack 通知は任意。
# =============================================================================

import os
from datetime import datetime
import io
import zipfile
import requests
from io import StringIO

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
    "SKAISETU.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER")
PASS = os.environ.get("WEATHERCASTER_PASS")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")  # 任意
# ---------------------------------------------------------------


def fetch_all_pdfs_to_zip_bytes(today_str: str) -> bytes:
    """
    すべての PDF を Basic 認証で取得し、ファイル名に日付プレフィックスを付けて
    メモリ上の ZIP にまとめて返す。失敗したPDFは .ERROR.txt を入れて記録。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in PDF_FILES:
            url = f"{BASE_URL}/{name}"
            try:
                r = requests.get(url, auth=(USER, PASS), timeout=60)
                if r.status_code == 200:
                    arcname = f"{today_str}_{name}"
                    zf.writestr(arcname, r.content)
                    print(f"[OK] {name} downloaded")
                else:
                    zf.writestr(
                        f"{today_str}_{name}.ERROR.txt",
                        f"HTTP {r.status_code} {url}",
                    )
                    print(f"[NG] {name} HTTP {r.status_code}")
            except Exception as e:
                zf.writestr(f"{today_str}_{name}.ERROR.txt", f"{url}\n{repr(e)}")
                print(f"[ERR] {name} {e}")
    return buf.getvalue()


def main():
    today = datetime.now().strftime("%Y%m%d")
    log_buf = StringIO()

    try:
        # 1) ダウンロード → ZIP（メモリ）
        zip_bytes = fetch_all_pdfs_to_zip_bytes(today)

        # 2) メール添付送信
        subject = f"Weathercaster 天気図 ZIP {today}"
        body = "気象庁Weathercasterの天気図PDFをZIP添付します（保存なし運用）。"
        msg_id = send_mail(
            to_addrs=os.environ.get("MAIL_TO", ""),
            subject=subject,
            body=body,
            attachment_blobs=[(f"weathercaster_{today}.zip", zip_bytes, "application/zip")],
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id}")

        # 3) 任意: Slack 通知（リンクではなく結果サマリ）
        if SLACK_CHANNEL_ID:
            send_slack_text(
                channel=SLACK_CHANNEL_ID,
                message=f":earth_asia: {today} Weathercaster ZIP をメール送信しました。\nMessage-ID: {msg_id}",
            )

    except Exception as e:
        if SLACK_CHANNEL_ID:
            send_slack_text(channel=SLACK_CHANNEL_ID, message=f":x: Weathercaster 送信失敗: {e}")
        raise


if __name__ == "__main__":
    main()
