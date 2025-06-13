# gpv_downloader.py
# ===============================================
# 指定イニシャル時刻から「3時間ごと12列」ペアDLユーティリティ
# 2025-06-13 by ChatGPT
# ===============================================

import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

def find_nearest_init(hours=[12, 0, 18, 6], now=None):
    """
    現在時刻に一番近いイニシャル時刻（12/00/18/06）を返す
    JST運用前提
    """
    if now is None:
        now = datetime.utcnow() + timedelta(hours=9)
    today = now.replace(minute=0, second=0, microsecond=0)
    base = today.replace(hour=0)
    diff = [(abs((today - base.replace(hour=h)).total_seconds()), h) for h in hours]
    nearest = min(diff)[1]
    # 未来のイニシャルは回避
    nearest_dt = base.replace(hour=nearest)
    if nearest_dt > today:
        nearest_dt -= timedelta(days=1)
    return nearest_dt


def download_gpv_multi_times(patterns, base_dir, init_dt, mirrors, ncols=12):
    """
    指定したinit_dtから3時間ごとにncols分（12列分）を
    すべてのパターンでペア取得する。
    - patterns: パターン配列（GSM or MSM用）
    - base_dir: 保存先ディレクトリ
    - init_dt: イニシャル時刻（datetime）
    - mirrors: ダウンロードURLリスト
    - ncols: 欲しい時刻の数（デフォルト12列）
    Return: [ [(ファイル1,時刻1),(ファイル2,時刻1)], ... 12時刻ぶん ]
    """
    os.makedirs(base_dir, exist_ok=True)
    ret = []
    for icol in range(ncols):
        target_time = init_dt + timedelta(hours=3*icol)
        ymd = target_time.strftime("%Y%m%d")
        y, m, d = target_time.strftime("%Y"), target_time.strftime("%m"), target_time.strftime("%d")
        h = target_time.hour
        files = []
        for pattern in patterns:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            found = False
            for url_base in mirrors:
                url = f"{url_base}/{y}/{m}/{d}/{fname}"
                out_path = os.path.join(base_dir, fname)
                try:
                    urllib.request.urlretrieve(url, out_path)
                    print(f"[OK] DL: {out_path}")
                    files.append((out_path, target_time))
                    found = True
                    break
                except Exception as e:
                    print(f"[NG] {fname}@{url_base}: {e}")
            if not found:
                break
        if len(files) == len(patterns):
            ret.append(files)
        else:
            print(f"[PAIR-NG] {target_time:%Y-%m-%d %H:%M}: ペア取得失敗")
            ret.append([])  # 欠損は空配列
    return ret

# --- 使用例（GSMならpatterns=GSM_PATTERNS, MSMならMSM_PATTERNS を渡す） ---
if __name__ == "__main__":
    GPV_MIRROR_URLS = [
        "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
    ]
    GSM_PATTERNS = [
        "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
        "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",
    ]
    base_dir = "./data"
    init_dt = find_nearest_init([12,0,18,6])
    print("[INFO] イニシャル時刻:", init_dt)
    ret = download_gpv_multi_times(GSM_PATTERNS, base_dir, init_dt, GPV_MIRROR_URLS, ncols=12)
    for icol, files in enumerate(ret):
        t = init_dt + timedelta(hours=3*icol)
        if files:
            print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL OK: {[f[0] for f in files]}")
        else:
            print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL NG")
