# gpv_downloader.py
# ===============================================
# 気象庁GPVデータ 6段×12列 横パネル自動DL & GRIB2→NetCDF変換
# -----------------------------------------------
# ・直近イニシャル時刻から3時間毎×12列DL（ペア/分割対応）
# ・GSM/MSM/局地いずれもパターン指定で運用可
# ・GRIB2→NetCDF一括変換
# ・ファイル名・DL仕様は公式配布構成に完全準拠
# -----------------------------------------------
# 2025-06-13 by ChatGPT
# ===============================================

import os
import urllib.request
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

# 公式のファイルパターン例（必要に応じて拡張可）
GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",
]
MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_Lsurf_FH36-39_grib2.bin",
]

def find_nearest_init(hours=[12, 0, 18, 6], now=None):
    """
    現在時刻に一番近いイニシャル時刻（00/06/12/18 UTC）を返す（JST基準）
    ※datetime型のreplace(minute=0, second=0, microsecond=0)で必ず時刻オブジェクトに
    """
    if now is None:
        now = datetime.utcnow() + timedelta(hours=9)  # JST
    # datetime型であることを保証
    today = now.replace(minute=0, second=0, microsecond=0)
    base = today.replace(hour=0)
    diff = [(abs((today - base.replace(hour=h)).total_seconds()), h) for h in hours]
    nearest = min(diff)[1]
    nearest_dt = base.replace(hour=nearest)
    if nearest_dt > today:
        nearest_dt -= timedelta(days=1)
    return nearest_dt

def download_gpv_panel(patterns, base_dir, init_dt, mirrors, ncols=12):
    """
    指定したinit_dtから3時間ごとにncols分（12列分）を
    すべてのパターンでペア取得する（GSM/MSM両対応）。
    欠損時は空配列で返す。
    Return: [ [(ファイル1,時刻1), (ファイル2,時刻1), ...], ... 12時刻ぶん ]
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

def grib2_to_nc(grib2_path):
    """GRIB2ファイルをNetCDFへ変換。既存関数と同じ仕様"""
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[grib2_to_nc] 実行コマンド: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8"
        )
        print("[grib2_to_nc] stdout:", result.stdout)
        print("[grib2_to_nc] stderr:", result.stderr)
    except subprocess.CalledProcessError as e:
        print("=== grib2→NetCDF変換でエラー ===")
        print("コマンド:", e.cmd)
        print("リターンコード:", e.returncode)
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)
        raise RuntimeError("grib2→nc変換に失敗しました（上記参照）") from e
    return str(nc_path)

# --- 使用例（GSM/MSMどちらも運用可） ---
if __name__ == "__main__":
    base_dir = "./data"
    init_dt = find_nearest_init([12, 0, 18, 6])
    print("[INFO] イニシャル時刻:", init_dt)
    # GSMならGSM_PATTERNS, MSMならMSM_PATTERNSを指定
    panel_files = download_gpv_panel(GSM_PATTERNS, base_dir, init_dt, GPV_MIRROR_URLS, ncols=12)
    for icol, files in enumerate(panel_files):
        t = init_dt + timedelta(hours=3*icol)
        if files:
            print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL OK: {[f[0] for f in files]}")
        else:
            print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL NG")
