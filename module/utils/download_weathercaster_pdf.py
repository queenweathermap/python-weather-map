# module/utils/download_weathercaster_pdf.py
# ===============================================================
# Weathercaster（会員制）天気図PDFをBasic認証でダウンロード
# ===============================================================

import os
import requests
from datetime import datetime

# 各PDFファイル名と説明
WEATHERCASTER_PDFS = {
    "COMP12.pdf": "12時間解析図",
    "COMP36.pdf": "36時間予想図",
    "COMP72.pdf": "72時間予想図",
    "FXJP854.pdf": "850hPa予想",
    "FXXN519.pdf": "500hPa渦度",
    "FZCX50.pdf": "地上予想",
    "FEFE19.pdf": "降水量予想",
}

BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

def download_weathercaster_pdfs(save_dir="./data", username=None, password=None):
    """指定ディレクトリにPDFをBasic認証で保存"""
    if not username or not password:
        raise ValueError("認証情報が指定されていません")

    os.makedirs(save_dir, exist_ok=True)
    saved_files = []

    for filename, label in WEATHERCASTER_PDFS.items():
        url = f"{BASE_URL}/{filename}"
        save_path = os.path.join(save_dir, f"{datetime.now().strftime('%Y%m%d')}_{filename}")

        res = requests.get(url, auth=(username, password))
        if res.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(res.content)
            print(f"[OK] {label} を保存しました: {save_path}")
            saved_files.append((label, save_path))
        else:
            print(f"[NG] {label} の取得失敗: {url} (status={res.status_code})")

    return saved_files  # [(label, path), ...]
