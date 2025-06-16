# gpv_downloader.py
# ===============================================
# GPV自動ダウンロード & grib2→NetCDF変換ユーティリティ
# -----------------------------------------------
# ジュピターで安定動作していたロジックを完全移植
# ・GSM/MSM/局地もパターン差替で運用OK
# ・NO DATA連発を徹底的に防止
# ・「今日/昨日 × 18,12,6,0UTC」で2ファイルとも取得
# -----------------------------------------------
# 2025-06-16 by ChatGPT
# ===============================================

import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

# ----------- 設定（パターン書換でMSM等もOK） ----------
GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]
GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",   # 気圧面
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",    # 地上
]

def download_available_gpv(pattern, base_dir, mirrors):
    """
    サーバ上で最新のGPVファイルを探してDL
    ・「今日→昨日」×「18,12,6,0UTC」で直近1ファイルDL
    ・成功時は (保存パス, 初期時刻) を返す
    """
    now = datetime.utcnow() + timedelta(hours=9)
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
        for h in [18, 12, 6, 0]:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            for url_base in mirrors:
                url = f"{url_base}/{y}/{m}/{d}/{fname}"
                out_path = os.path.join(base_dir, fname)
                print(f"[TRY] {url}")
                try:
                    urllib.request.urlretrieve(url, out_path)
                    print(f"[OK] DL: {out_path}")
                    return out_path, datetime(dt.year, dt.month, dt.day, h)
                except Exception as e:
                    print(f"[NG] {url.split('/')[-1]}: {e}")
    print(f"[ERROR] {pattern} どれもDLできず")
    return None, None

def grib2_to_nc(grib2_path):
    """
    GRIB2→NetCDF変換（wgrib2使用・サイズチェック付き）
    """
    grib2_path = Path(grib2_path)
    if not grib2_path.exists() or os.path.getsize(grib2_path) < 10 * 1024:
        print(f"[SKIP] ダウンロード失敗or空ファイル: {grib2_path}")
        return None
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[wgrib2] 実行: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8"
        )
        print("[wgrib2] stdout:", result.stdout)   # ←ここ
        print("[wgrib2] stderr:", result.stderr)   # ←ここ
    except subprocess.CalledProcessError as e:
        print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        print(f"[wgrib2 error]: {e.stderr}")       # ←ここも追加
        return None

        print("[wgrib2] stdout:", result.stdout)
        print("[wgrib2] stderr:", result.stderr)
    except subprocess.CalledProcessError:
        print(f"[SKIP] NetCDF変換失敗: {nc_path}")
        return None
    if not nc_path.exists() or os.path.getsize(nc_path) < 10 * 1024:
        print(f"[SKIP] NetCDF出力異常: {nc_path}")
        return None
    return str(nc_path)

# --------------------- メイン ---------------------
if __name__ == "__main__":
    base_dir = "./data"
    os.makedirs(base_dir, exist_ok=True)

    # 2ファイル（気圧面・地上）それぞれ個別に最新DL
    grib2_files = []
    nc_paths = []
    init_time = None

    for pattern in GSM_PATTERNS:
        grib2_path, itime = download_available_gpv(pattern, base_dir, GPV_MIRROR_URLS)
        if grib2_path is not None and itime is not None:
            grib2_files.append(grib2_path)
            if init_time is None:
                init_time = itime

    # 必要な2ファイルがそろわなければNO DATA
    if len(grib2_files) < 2:
        print("【ERROR】気圧面・地上のGRIB2ファイルが両方揃いません（NO DATA）")
        # ここでNO DATA画像生成 or 終了
        exit(1)

    # GRIB2→NetCDF変換
    for path in grib2_files:
        nc = grib2_to_nc(path)
        if nc is not None:
            nc_paths.append(nc)

    # 両方変換OKか確認
    if len(nc_paths) < 2:
        print("【ERROR】NetCDF変換が両方成功せず（NO DATA）")
        exit(1)

    print(f"[INFO] 2つのNetCDF OK: {nc_paths}")
    print(f"[INFO] Init time: {init_time}")

    # ここでxarray.open_dataset等で合成し、以降のパネル描画等へ進む
    # （描画処理は別モジュールに記述を推奨）
