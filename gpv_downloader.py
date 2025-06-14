# gpv_downloader.py
# ===============================================
# 気象庁GPVデータ 6段×12列 横パネル自動DL & GRIB2→NetCDF変換
# -----------------------------------------------
# ・直近イニシャル時刻から3時間毎×12列DL（ペア/分割対応）
# ・GSM/MSM/局地いずれもパターン指定で運用可
# ・GRIB2→NetCDF一括変換
# ・ファイル名・DL仕様は公式配布構成に完全準拠
# -----------------------------------------------
# 2025-06-14 by ChatGPT
# ===============================================

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import requests

GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

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

def find_nearest_init(hours, now=None):
    """現在時刻に一番近いイニシャル時刻（例: [0,3,6,9,12,15,18,21]）を返す（JST基準）"""
    if now is None:
        now = datetime.utcnow() + timedelta(hours=9)  # JST
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now)
        except Exception:
            now = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
    elif hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    today = now.replace(minute=0, second=0, microsecond=0)
    base = today.replace(hour=0)
    diff = [(abs((today - base.replace(hour=h)).total_seconds()), h) for h in hours]
    nearest = min(diff)[1]
    nearest_dt = base.replace(hour=nearest)
    if nearest_dt > today:
        nearest_dt -= timedelta(days=1)
    return nearest_dt

def find_existing_init_dt(patterns, base_dir, mirrors, hours):
    """
    サーバ上に実際に全パターンファイルが存在する最新イニシャル時刻を返す
    """
    now = datetime.utcnow() + timedelta(hours=9)  # JST
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
        for h in sorted(hours, reverse=True):  # 新しい時刻から順に
            all_exists = True
            for pattern in patterns:
                fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
                exists_this = False
                for url_base in mirrors:
                    url = f"{url_base}/{y}/{m}/{d}/{fname}"
                    try:
                        r = requests.head(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                        if r.status_code == 200:
                            exists_this = True
                            break
                    except Exception:
                        continue
                if not exists_this:
                    all_exists = False
                    break
            if all_exists:
                return dt.replace(hour=h, minute=0, second=0, microsecond=0)
    return None

def download_with_requests(url, out_path):
    """
    User-Agent付きでファイルDL、落ちなければTrue
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
        print(f"[OK] DL: {out_path}")
        return True
    except Exception as e:
        print(f"[NG][requests] {url}: {e}")
        return False

def download_with_curl(url, out_path):
    """
    curlによるダウンロード（リトライ・User-Agent・follow-redirects付き）
    """
    cmd = ["curl", "-L", "-A", "Mozilla/5.0", "-o", out_path, url]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"[OK][curl] DL: {out_path}")
        return True
    else:
        print(f"[NG][curl] {url}")
        return False

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
        target_time = init_dt + timedelta(hours=3 * icol)
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
                # ---- 1. requestsでDL
                found = download_with_requests(url, out_path)
                if not found:
                    # ---- 2. curl fallback
                    found = download_with_curl(url, out_path)
                if found:
                    files.append((out_path, target_time))
                    break
            if not found:
                break
        if len(files) == len(patterns):
            ret.append(files)
        else:
            print(f"[PAIR-NG] {target_time:%Y-%m-%d %H:%M}: ペア取得失敗")
            ret.append([])  # 欠損は空配列
    return ret

def grib2_to_nc(grib2_path):
    """GRIB2ファイルをNetCDFへ変換（サイズチェック付き）"""
    grib2_path = Path(grib2_path)
    # GRIB2ファイルサイズが極端に小さい場合はスキップ（例: 10KB未満）
    if not grib2_path.exists() or os.path.getsize(grib2_path) < 10 * 1024:
        print(f"[SKIP] ダウンロード失敗or空ファイル: {grib2_path}")
        return None
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
    except subprocess.CalledProcessError:
        print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        return None
    # NetCDF出力もサイズが小さすぎる場合は失敗扱い
    if not nc_path.exists() or os.path.getsize(nc_path) < 10 * 1024:
        print(f"[SKIP] NetCDF出力異常: {nc_path}")
        return None
    return str(nc_path)

# --- 使用例 ---
if __name__ == "__main__":
    base_dir = "./data"
    # MSM運用例（hoursはGSM/局地で切り替え可）
    init_dt = find_existing_init_dt(
        MSM_PATTERNS,
        base_dir=base_dir,
        mirrors=GPV_MIRROR_URLS,
        hours=[0, 3, 6, 9, 12, 15, 18, 21]
    )
    print("[INFO] サーバ存在確認済みイニシャル時刻:", init_dt)
    if init_dt is None:
        print("【ERROR】サーバ上に利用可能なイニシャル時刻がありません")
    else:
        panel_files = download_gpv_panel(MSM_PATTERNS, base_dir, init_dt, GPV_MIRROR_URLS, ncols=12)
        for icol, files in enumerate(panel_files):
            t = init_dt + timedelta(hours=3*icol)
            if files:
                print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL OK: {[f[0] for f in files]}")
            else:
                print(f"[{icol:02d}] {t:%Y-%m-%d %H:%M} DL NG")

        # NetCDF変換サンプル（None除外必須！）
        if panel_files:
            # 1. 空リストも除外しつつフラット化
            file_list = [item for sublist in panel_files[:3] if sublist for item in sublist]
            nc_paths = []
            for path, _ in file_list:
                nc = grib2_to_nc(path)
                if nc and os.path.exists(nc):
                    nc_paths.append(nc)
            print("nc_paths:", nc_paths)
        else:
            print("[SKIP] パネルファイルがありません")

