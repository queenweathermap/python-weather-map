# gpv_downloader.py
# ===============================================================
# GPVファイルのダウンロード・自動パネル描画ユーティリティ
# MSM/GSM/LFM/ローカルもモデル名で一括運用（index.htmlパースも可）
# 2025-06-22 by ChatGPT
# ===============================================================

import os
import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

# --- モデル定義 ---
MODEL_CONFIG = {
    "GSM": {
        "patterns": [
            "GSM_GPV_Rjp_Gll0p1deg_L-pall",
            "GSM_GPV_Rjp_Gll0p1deg_Lsurf"
        ],
        "panel_func": "make_gsm_panel",
    },
    "MSM": {
        "patterns": [
            "MSM_GPV_Rjp_L-pall",
            "MSM_GPV_Rjp_Lsurf"
        ],
        "panel_func": "make_msm_panel",
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

def download_gpv_panel(patterns, base_dir, init_dt, mirror_urls, ncols=12):
    """
    各パターン・時刻のGRIB2ファイルを自動ダウンロード
    欠損があってもNone埋めで返す
    """
    out_list = []
    for i in range(ncols):
        t = init_dt + pd.Timedelta(hours=3*i)
        ymdh = t.strftime("%Y%m%d%H")
        col = []
        for pattern in patterns:
            # MSM/LFMはstepまとめ
            fh_idx = i // 16
            fh = FH_LIST[fh_idx] if fh_idx < len(FH_LIST) else FH_LIST[-1]
            files = list_files_on_server(t, pattern, fh)
            fname = None
            if files:
                # 時刻・パターン・FHに合う一番新しいもの
                fname = sorted(files)[-1]
            if fname:
                y, m, d = t.strftime("%Y"), t.strftime("%m"), t.strftime("%d")
                url = f"{mirror_urls[0]}/{y}/{m}/{d}/{fname}"
                fpath = os.path.join(base_dir, fname)
                if not os.path.exists(fpath):
                    try:
                        urllib.request.urlretrieve(url, fpath)
                        print(f"[OK] DL: {fpath}")
                    except Exception as e:
                        print(f"[NG] {fname}: {e}")
                        col.append(None)
                        continue
                col.append((fpath, t))
            else:
                col.append(None)
        out_list.append(col if all(col) else None)
    return out_list
