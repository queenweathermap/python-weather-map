# scripts/daily_weathercaster_notify.py
# ===============================================================
# 気象庁Weathercaster PDF天気図を一括DL→JPG変換→ZIP化
# → Google Driveへアップ→Slack通知→古いファイル自動削除
# ---------------------------------------------------------------
# ZIP圧縮: module.utils.zip_utils.zip_files を利用
# Drive/Slack: 共通ユーティリティ呼び出し
# ===============================================================

import os
import requests
from datetime import datetime
import subprocess
from io import StringIO
import sys

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files
from module.utils.slack_utils import send_slack_text

# --- 保存先ディレクトリ ---
SAVE_DIR = "./data"
os.makedirs(SAVE_DIR, exist_ok=True)

# --- ダウンロード対象PDF ---
PDF_FILES = [
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXJP854.pdf", "FXXN519.pdf", "FZCX50.pdf", "FEFE19.pdf"
]
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

today = datetime.now().strftime("%Y%m%d")
USER = os.environ["WEATHERCASTER_USER"]
PASS = os.environ["WEATHERCASTER_PASS"]
DRIVE_FOLDER_ID = os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

# --- ログ捕捉セットアップ ---
log_buffer = StringIO()
sys.stdout = sys.stderr = log_buffer

print(f"[START] {today} Weathercaster天気図自動処理")

try:
    # --- STEP 1: PDF一括ダウンロード ---
    print("[STEP1] PDF一括ダウンロード")
    pdf_paths = []
    for fname in PDF_FILES:
        url = f"{BASE_URL}/{fname}"
        save_path = os.path.join(SAVE_DIR, f"{today}_{fname}")
        try:
            res = requests.get(url, auth=(USER, PASS))
            if res.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(res.content)
                print(f"[OK] {fname} 保存: {save_path}")
                pdf_paths.append(save_path)
            else:
                print(f"[NG] {fname} ダウンロード失敗: {res.status_code} ({url})")
        except Exception as e:
            print(f"[ERR] {fname} エラー: {e}")

    # --- STEP 2: PDF→JPG変換（300dpi） ---
    print("[STEP2] PDF→JPG変換（300dpi）")
    jpg_paths = []
    for pdf_path in pdf_paths:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        jpg_path = os.path.join(SAVE_DIR, f"{base}.jpg")
        cmd = f"pdftoppm -jpeg -singlefile -r 300 {pdf_path} {jpg_path[:-4]}"
        try:
            subprocess.run(cmd, shell=True, check=True)
            if os.path.exists(jpg_path):
                print(f"[OK] JPG変換: {jpg_path}")
                jpg_paths.append(jpg_path)
            else:
                print(f"[NG] JPG変換失敗: {jpg_path}")
        except Exception as e:
            print(f"[NG] JPG変換失敗: {jpg_path} - {e}")

    # --- STEP 3: ZIP圧縮（共通関数利用） ---
    print("[STEP3] JPGをZIP圧縮")
    zip_path = os.path.join(SAVE_DIR, f"{today}_weathercharts.zip")
    zip_files(jpg_paths, zip_path)
    print(f"[OK] ZIP作成: {zip_path}")

    # --- STEP 4: Google Driveにアップ ---
    print("[STEP4] Google Driveへアップロード")
    drive_url = upload_to_drive(zip_path, folder_id=DRIVE_FOLDER_ID)
    print(f"[OK] Drive URL: {drive_url}")

    # --- STEP 5: Slack通知（ログ＋URLのみ） ---
    print("[STEP5] Slack通知")
    full_log = log_buffer.getvalue()
    msg = (
        f":white_check_mark: {today} Weathercaster天気図 処理完了\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url}\n"
        f"--- LOG ---\n```{full_log[-1800:]}```"
    )
    send_slack_text(channel=SLACK_CHANNEL_ID, message=msg)

    # --- STEP 6: Drive古いファイル削除（30日以上） ---
    print("[STEP6] Google Drive内の古いファイル削除")
    try:
        delete_old_files_from_drive(folder_id=DRIVE_FOLDER_ID, older_than_days=30)
    except TypeError:
        from dotenv import load_dotenv
        load_dotenv()
        creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        delete_old_files_from_drive(folder_id=DRIVE_FOLDER_ID, creds_json=creds_json, days=30)

except Exception as e:
    error_log = log_buffer.getvalue()
    send_slack_text(
        channel=SLACK_CHANNEL_ID,
        message=f":x: {today} エラー発生\n```{str(e)}\n{error_log[-1500:]}```"
    )
    raise

finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_buffer.close()

print("[DONE] Weathercaster Notify 完了")
