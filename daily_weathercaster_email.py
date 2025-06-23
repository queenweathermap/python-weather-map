# daily_weathercaster_email.py
# ===============================================================
# Weathercaster 天気図PDFを → JPG変換して → メールに添付送信（Drive保存なし）
# ---------------------------------------------------------------
# ・対象PDFは全種類（COMP12など）
# ・PDF → JPGに変換（1ページ目想定）
# ・添付ファイルは1通のメールにまとめて送信
# ・送信先は wx@queenw.com に固定
# ・SMTP設定は .env または mail_utils.py の引数で制御
# ===============================================================

import os
from dotenv import load_dotenv
from module.utils.download_weathercaster_pdf import download_weathercaster_pdfs
from module.utils.mail_utils import send_mail
from pdf2image import convert_from_path

# --- .env 読み込み ---
load_dotenv()

# --- 固定送信先 ---
TO_ADDR = "wx@queenw.com"

# --- 保存先ディレクトリ ---
SAVE_DIR = "./data"
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 1. Weathercaster PDFを全件DL ---
USER = os.getenv("WEATHERCASTER_USER")
PASS = os.getenv("WEATHERCASTER_PASS")
files = download_weathercaster_pdfs(save_dir=SAVE_DIR, username=USER, password=PASS)

# --- 2. PDF → JPGに変換（1ページ目のみ） ---
image_paths = []
for label, pdf_path in files:
    try:
        pages = convert_from_path(pdf_path, dpi=200)
        if pages:
            jpg_path = pdf_path.replace(".pdf", ".jpg")
            pages[0].save(jpg_path, "JPEG")
            image_paths.append(jpg_path)
            print(f"[OK] JPG変換: {jpg_path}")
        else:
            print(f"[SKIP] PDFが空: {pdf_path}")
    except Exception as e:
        print(f"[ERROR] JPG変換失敗: {pdf_path} - {e}")

# --- 3. メールにまとめて送信 ---
if image_paths:
    import zipfile
    zip_path = os.path.join(SAVE_DIR, "weathercharts.zip")
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for img in image_paths:
            zipf.write(img, arcname=os.path.basename(img))
    send_mail(
        to_addr=to_addr,
        subject=subject,
        body=body,
        attachment_paths=jpg_files,  # 正しい引数名に変更
        ...
    )
else:
    print("[INFO] 添付対象なし（メール送信スキップ）")
