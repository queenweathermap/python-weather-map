# scripts/daily_weathercaster_notify.py
# ===============================================================
# 気象庁Weathercaster PDF天気図一括DL→JPG→
# COMP_ALLとFXXN_FZCXは横連結mergeだけ生成・保存
# SKAISETUは縦連結mergeだけ生成・保存
# 単独PDFは1ページ目jpgのみ生成・保存
# デスクトップには「merge系」のみコピー
# ===============================================================

import os
from dotenv import load_dotenv
load_dotenv()
import requests
from datetime import datetime
import subprocess
from io import StringIO
import sys
from PIL import Image
import shutil

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files
from module.utils.slack_utils import send_slack_text
from dotenv import load_dotenv


SAVE_DIR = "./data"
os.makedirs(SAVE_DIR, exist_ok=True)

PDF_GROUPS = [
    ("COMP_ALL",   ["COMP12.pdf", "COMP36.pdf", "COMP72.pdf"]),   # 横連結
    ("FXXN_FZCX",  ["FXXN519.pdf", "FZCX50.pdf"]),               # 横連結
    ("FXJP854",    ["FXJP854.pdf"]),                             # 単独
    ("FEFE19",     ["FEFE19.pdf"]),                              # 単独
    ("TKAISETU",   ["TKAISETU.pdf"]),                            # 単独
    ("SKAISETU",   ["SKAISETU.pdf"]),                            # ←全ページ縦連結
]

PDF_FILES = sorted(list({pdf for group in PDF_GROUPS for pdf in group[1]}))

BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"
today = datetime.now().strftime("%Y%m%d")
USER = os.environ["WEATHERCASTER_USER"]
PASS = os.environ["WEATHERCASTER_PASS"]
DRIVE_FOLDER_ID = os.environ["WEATHERCASTER_DRIVE_FOLDER_ID"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

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

    # --- STEP 2: PDF→JPG全ページ変換 ---
    print("[STEP2] PDF→JPG全ページ変換（300dpi）")
    pdf_page_jpgs = {}  # {pdf_base: [jpg1, jpg2, ...]}
    for pdf_path in pdf_paths:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        out_base = os.path.join(SAVE_DIR, base)
        cmd = f"pdftoppm -jpeg -r 300 {pdf_path} {out_base}"
        try:
            subprocess.run(cmd, shell=True, check=True)
            # 1ページ目から順にjpgファイルを記録
            page = 1
            page_jpgs = []
            while True:
                jpg_path = f"{out_base}-{page}.jpg"
                if os.path.exists(jpg_path):
                    page_jpgs.append(jpg_path)
                    print(f"[OK] JPG変換: {jpg_path}")
                    page += 1
                else:
                    break
            if page_jpgs:
                pdf_page_jpgs[base] = page_jpgs
            else:
                print(f"[NG] JPG変換失敗: {pdf_path}")
        except Exception as e:
            print(f"[NG] JPG変換失敗: {pdf_path} - {e}")

    # --- STEP 3: グループごと連結＋デスクトップ保存（merge系のみ） ---
    print("[STEP3] グループごとmerge生成＋デスクトップ保存")
    jpg_group_paths = []
    for group_name, group_pdfs in PDF_GROUPS:
        if group_name == "SKAISETU":
            # SKAISETUは全ページを縦連結
            page_jpgs = []
            for pdf in group_pdfs:
                base = f"{today}_{os.path.splitext(pdf)[0]}"
                n = 1
                while True:
                    jpg_path = f"{SAVE_DIR}/{base}-{n}.jpg"
                    if os.path.exists(jpg_path):
                        page_jpgs.append(jpg_path)
                        n += 1
                    else:
                        break
            imgs = [Image.open(jpg) for jpg in page_jpgs]
            if not imgs:
                print(f"[WARN] SKAISETUのJPGが見つかりません")
                continue
            max_width = max(img.width for img in imgs)
            total_height = sum(img.height for img in imgs)
            merged_img = Image.new('RGB', (max_width, total_height), (255,255,255))
            y_offset = 0
            for img in imgs:
                merged_img.paste(img, (0, y_offset))
                y_offset += img.height
            merged_path = os.path.join(SAVE_DIR, f"{today}_{group_name}_merge.jpg")
            merged_img.save(merged_path)
            jpg_group_paths.append(merged_path)
            print(f"[OK] SKAISETU縦連結画像保存: {merged_path}")
        #  desktop_path = os.path.expanduser(f"~/Desktop/{today}_{group_name}_merge.jpg")
        #  merged_img.save(desktop_path)
        #  print(f"[OK] デスクトップにも保存: {desktop_path}")
        elif group_name in ["COMP_ALL", "FXXN_FZCX"]:
            # 横連結グループのみmerge
            jpgs = []
            for pdf in group_pdfs:
                base = f"{today}_{os.path.splitext(pdf)[0]}"
                jpg_1st = f"{SAVE_DIR}/{base}-1.jpg"
                if os.path.exists(jpg_1st):
                    jpgs.append(jpg_1st)
            imgs = [Image.open(jpg) for jpg in jpgs]
            if not imgs:
                print(f"[WARN] グループ {group_name} のJPGが見つかりません")
                continue
            total_width = sum(img.width for img in imgs)
            max_height = max(img.height for img in imgs)
            merged_img = Image.new('RGB', (total_width, max_height), (255,255,255))
            x_offset = 0
            for img in imgs:
                merged_img.paste(img, (x_offset, 0))
                x_offset += img.width
            merged_path = os.path.join(SAVE_DIR, f"{today}_{group_name}_merge.jpg")
            merged_img.save(merged_path)
            jpg_group_paths.append(merged_path)
            print(f"[OK] 横一列連結画像保存: {merged_path}")
        #  desktop_path = os.path.expanduser(f"~/Desktop/{today}_{group_name}_merge.jpg")
        #  merged_img.save(desktop_path)
        #  print(f"[OK] デスクトップにも保存: {desktop_path}")
        else:
            # 単独PDFは1ページ目だけ（mergeなし）
            pdf = group_pdfs[0]
            base = f"{today}_{os.path.splitext(pdf)[0]}"
            jpg_1st = f"{SAVE_DIR}/{base}-1.jpg"
            if os.path.exists(jpg_1st):
                jpg_group_paths.append(jpg_1st)
          #  desktop_path = os.path.expanduser(f"~/Desktop/{base}-1.jpg")
          #  shutil.copy(jpg_1st, desktop_path)
          #   print(f"[OK] 単独画像をデスクトップ保存: {desktop_path}")

    # --- STEP 4: ZIP圧縮（merge/単独のみ） ---
    print("[STEP4] JPGをZIP圧縮")
    zip_path = os.path.join(SAVE_DIR, f"{today}_weathercharts.zip")
    zip_files(jpg_group_paths, zip_path)
    print(f"[OK] ZIP作成: {zip_path}")

    # --- STEP 5: Google Driveにアップ ---
    print("[STEP5] Google Driveへアップロード")
    drive_url = upload_to_drive(zip_path, folder_id=DRIVE_FOLDER_ID)
    print(f"[OK] Drive URL: {drive_url}")

    # --- STEP 6: Slack通知（ログ＋URLのみ） ---
    print("[STEP6] Slack通知")
    full_log = log_buffer.getvalue()
    msg = (
        f":earth_asia: {today} Weathercaster天気図 処理完了\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url}\n"
        f"--- LOG ---\n```{full_log[-1800:]}```"
    )
    send_slack_text(channel=SLACK_CHANNEL_ID, message=msg)

    # --- STEP 7: Drive古いファイル削除（30日以上） ---
    print("[STEP7] Google Drive内の古いファイル削除")
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
