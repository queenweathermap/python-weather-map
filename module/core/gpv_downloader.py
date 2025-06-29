# ===============================================================
# module/core/gpv_downloader.py
# GPVファイルのダウンロード・自動サイクル判定ユーティリティ
# MSM/GSM/LFMもモデル名で一括運用（index.htmlパース対応）
# 2025-06-29 ChatGPT
# ===============================================================

import os
import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# --- モデル定義 ---
MODEL_CONFIG = {
    "GSM": {
        "patterns": [
            "GSM_GPV_Rjp_Gll0p1deg_L-pall",
            "GSM_GPV_Rjp_Gll0p1deg_Lsurf"
        ]
    },
    "MSM": {
        "patterns": [
            "MSM_GPV_Rjp_L-pall",
            "MSM_GPV_Rjp_Lsurf"
        ]
    }
    # 必要に応じて拡張
}

GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

FH_LIST = ["FH00-15", "FH16-33", "FH34-39", "FH40-51", "FH52-78"]

def list_files_on_server(date: datetime, pattern: str, fh: str):
    """index.htmlをパースしてサーバ上のファイル一覧を返す"""
    y, m, d = date.strftime("%Y"), date.strftime("%m"), date.strftime("%d")
    url = f"{GPV_MIRROR_URLS[0]}/{y}/{m}/{d}/"
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

def download_gpv_file(url, fpath):
    """指定URLのGPVファイルをDL（存在チェックあり）"""
    if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
        print(f"[OK] already exists: {fpath}")
        return fpath
    try:
        urllib.request.urlretrieve(url, fpath)
        print(f"[OK] DL: {fpath}")
        return fpath
    except Exception as e:
        print(f"[NG] {fpath}: {e}")
        return None

def find_latest_available_files(
    base_dir="./data", 
    days_back=2,
    model="GSM", 
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3], # 最新サイクル優先
    fh_band="FD0000-0100" # GSM例
):
    """index.htmlをパースしてモデルごとの最新ファイルを抽出する"""
    patterns = MODEL_CONFIG[model]["patterns"]
    base_url = GPV_MIRROR_URLS[0]
    now = datetime.utcnow()
    for day_delta in range(days_back):
        day = now - timedelta(days=day_delta)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            # 各パターン・FH帯でファイル探索
            found_files = []
            for pattern in patterns:
                files = list_files_on_server(dt, pattern, fh_band)
                if not files:
                    break
                fname = files[0]
                found_files.append((fname, pattern))
            if len(found_files) == len(patterns):
                y, m, d, hh = dt.strftime("%Y %m %d %H").split()
                data_url = f"{base_url}/{y}/{m}/{d}/"
                file_infos = []
                for fname, pattern in found_files:
                    file_infos.append({
                        "url": f"{data_url}{fname}",
                        "local": os.path.join(base_dir, fname)
                    })
                # ymd, hh = "20250628", "21" など
                return y+m+d, hh, file_infos
    raise FileNotFoundError(f"利用可能な{model} GPVファイルがindex.html上に見つかりません")

# 追加：MSM/LFM向けには同様のループでパターン・FHを調整して呼び出し
