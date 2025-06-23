# daily_weathercaster_email.py
# ===============================================================
# Weathercaster 天気図PDFを → JPG変換して → メール添付送信
# ---------------------------------------------------------------
# ・PDFは全種DL（COMP12など）
# ・PDF→JPG（1ページ目のみ）
# ・JPGをzipにまとめて1通で送信
# ===============================================================

import os
from dotenv import load_dotenv
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.mail_utils import send_mail
from pdf2image import convert_from_path
import zipfile

# --- .env読込 ---
load_dotenv()

# --- 固定設定 ---
TO_ADDR = "wx@queenw.com"
SAVE_DIR = "./data"
SUBJECT = "【自動送信】本日の天気図（Weathercasterより）"
BODY = "本日分のWeathercaster天気図を添付いたします。\nご確認ください。"

os.makedirs(SAVE_DIR, exist_ok=True)

# --- 1. PDFダウンロード ---
USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
pdf_files = download_weathercaster_pdfs(save_dir=SAVE_DIR, username=USER, password=PASS)

# --- 2. PDF → JPG変換 ---
jpg_paths = []
for label, pdf_path in pdf_files:
    try:
        pages = convert_from_path(pdf_path, dpi=200)
        if pages:
            jpg_path = pdf_path.replace(".pdf", ".jpg")
            pages[0].save(jpg_path, "JPEG")
            jpg_paths.append(jpg_path)
            print(f"[OK] JPG変換: {jpg_path}")
        else:
            print(f"[SKIP] PDFが空: {pdf_path}")
    except Exception as e:
        print(f"[ERROR] JPG変換失敗: {pdf_path} - {e}")

# --- 3. メール送信（JPGまとめてzip添付） ---
if jpg_paths:
    zip_path = os.path.join(SAVE_DIR, "weathercharts.zip")
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for img_path in jpg_paths:
            zipf.write(img_path, arcname=os.path.basename(img_path))
    send_mail(
        to_addr=TO_ADDR,
        subject=SUBJECT,
        body=BODY,
        attachment_paths=[zip_path]
    )
else:
    print("[INFO] 添付ファイルなし、メール送信スキップ")
