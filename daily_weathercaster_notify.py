# daily_weathercaster_notify.py
# ===============================================================
# Weathercaster 天気図PDFを → JPG変換して → Slackにzipで送信
# ---------------------------------------------------------------
# ・PDFは全種DL（COMP12など）
# ・PDF→JPG（1ページ目のみ）
# ・JPGをzipにまとめてSlackチャンネルに送信
# ・チャンネルID／トークンは .env または Secrets 経由で取得
# ===============================================================

import os
import zipfile
from dotenv import load_dotenv
from pdf2image import convert_from_path

from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.slack_utils import upload_file_slack

# --- 環境変数読込 ---
load_dotenv()

# --- 保存ディレクトリ & Slack設定 ---
SAVE_DIR = "./data"
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 定数メッセージ ---
TITLE = "本日の天気図"
COMMENT = "Weathercaster提供の最新天気図（JPGまとめ）をお届けします。"

# --- 1. Weathercaster PDF全種ダウンロード ---
USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
pdf_files = download_weathercaster_pdfs(save_dir=SAVE_DIR, username=USER, password=PASS)

# --- 2. PDF → JPG（1ページ目のみ） ---
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

# --- 3. JPG群をzip化してSlack送信 ---
if jpg_paths:
    zip_path = os.path.join(SAVE_DIR, "weathercharts.zip")
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for img_path in jpg_paths:
            zipf.write(img_path, arcname=os.path.basename(img_path))

    upload_file_slack(
        channel=SLACK_CHANNEL,
        filepath=zip_path,
        title=TITLE,
        initial_comment=COMMENT
    )
else:
    print("[INFO] 添付ファイルなし、Slack送信スキップ")
