# gpv_downloader.py
# ===============================================
# MSM/GSM/LFM/ローカル対応 index.htmlパース＆DL最小サンプル
# 2025-06-22 by ChatGPT
# ===============================================

import os
import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

GPV_MIRROR_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
FH_LIST = ["FH00-15", "FH16-33", "FH34-39", "FH40-51", "FH52-78"]
PATTERN = "MSM_GPV_Rjp_Lsurf"  # ★ここをMSM/GSM/LFMで切り替えて運用可

def list_files_on_server(date: datetime, pattern: str, fh: str):
    """index.htmlをパースしてサーバ上のファイル一覧を返す"""
    y, m, d = date.strftime("%Y"), date.strftime("%m"), date.strftime("%d")
    url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/"
    try:
        with urllib.request.urlopen(url) as res:
            soup = BeautifulSoup(res.read(), "html.parser")
            return [
                a["href"] for a in soup.find_all("a", href=True)
                if pattern in a["href"] and fh in a["href"] and a["href"].endswith("grib2.bin")
            ]
    except Exception as e:
        print(f"[WARN] index.html取得失敗: {url} ({e})")
        return []

def find_latest_available_gpv(pattern, fh_list):
    """サーバで最新の実在ファイルを探索"""
    now = datetime.utcnow() + timedelta(hours=9)
    for day_offset in range(0, 3):
        dt = now - timedelta(days=day_offset)
        for h in [0, 3, 6, 9, 12, 15, 18, 21]:
            for fh in fh_list:
                files = list_files_on_server(dt.replace(hour=h), pattern, fh)
                if files:
                    fname = sorted(files)[-1]
                    print(f"[FOUND] {fname}")
                    y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
                    url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/{fname}"
                    return url, fname
    print(f"[ERROR] {pattern}でファイル見つからず")
    return None, None

def download_latest_gpv(pattern=PATTERN, base_dir="./data", fh_list=FH_LIST):
    """index.htmlで実在ファイルだけDL"""
    url, fname = find_latest_available_gpv(pattern, fh_list)
    if url:
        os.makedirs(base_dir, exist_ok=True)
        out_path = os.path.join(base_dir, fname)
        try:
            urllib.request.urlretrieve(url, out_path)
            print(f"[OK] DL: {out_path}")
            return out_path
        except Exception as e:
            print(f"[NG] {fname}: {e}")
    else:
        print("[NO DATA] ダウンロードできませんでした")
    return None

# ========= 最小動作確認 =========
if __name__ == "__main__":
    # MSMのLsurf最新をDL（他のパターンや日付もこのロジックでOK）
    download_latest_gpv()
