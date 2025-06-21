# module/utils/download_weathercaster_pdf.py
# ===============================================================
# Weathercaster（会員制）天気図PDFをBasic認証で一括ダウンロードするモジュール
# ---------------------------------------------------------------
# ・固定URL構造を持つPDF（COMP12.pdfなど）を毎日取得
# ・ファイル名は日付付き（例: 20250621_COMP12.pdf）で保存
# ・Basic認証によりアクセス制限付きページから取得
# ・失敗時はログ出力（ステータスコード確認）
# ===============================================================

import os
import requests
from datetime import datetime

# --- 対象のPDFファイルとラベル定義 ---
WEATHERCASTER_PDFS = {
    "COMP12.pdf": "12時間解析図",
    "COMP36.pdf": "36時間予想図",
    "COMP72.pdf": "72時間予想図",
    "FXJP854.pdf": "850hPa予想",
    "FXXN519.pdf": "500hPa渦度",
    "FZCX50.pdf": "地上予想",
    "FEFE19.pdf": "降水量予想",
}

# --- 基本URL（ファイル名を末尾に付加） ---
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

def download_weathercaster_pdfs(save_dir="./data", username=None, password=None):
    """
    会員制Weathercaster天気図PDFを一括ダウンロード
    - Basic認証（username/password）を使用
    - 日付入りファイル名でローカル保存

    Returns: List[Tuple[str, str]] = [(ラベル, 保存先パス), ...]
    """
    if not username or not password:
        raise ValueError("認証情報が指定されていません")

    os.makedirs(save_dir, exist_ok=True)
    saved_files = []

    for filename, label in WEATHERCASTER_PDFS.items():
        url = f"{BASE_URL}/{filename}"
        date_prefix = datetime.now().strftime("%Y%m%d")
        save_path = os.path.join(save_dir, f"{date_prefix}_{filename}")

        try:
            res = requests.get(url, auth=(username, password))
            if res.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(res.content)
                print(f"[OK] {label} を保存しました: {save_path}")
                saved_files.append((label, save_path))
            else:
                print(f"[NG] {label} の取得失敗: {url} (status={res.status_code})")
        except Exception as e:
            print(f"[ERROR] {label} の取得エラー: {e}")

    return saved_files
