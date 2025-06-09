# ===============================
# GPV（GSM/MSM）自動ダウンロード & grib2→NetCDF変換ユーティリティ
# ===============================

import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

# --- パターンを辞書で管理 ---
GPV_PATTERNS = {
    "GSM": "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
    "MSM": "MSM_GPV_Rjp_L-pall_FD0000-0100_grib2.bin"
}
BASE_DIR = "./data"

# ===============================
# 共通：GPVファイルダウンロード（GSM/MSM両対応）
# ===============================
def download_gpv(model="GSM", pattern=None, base_dir=BASE_DIR):
    """
    GSM/MSM両対応のGPVファイルダウンロード（最新のファイルを探索・取得）
    Args:
        model: "GSM" or "MSM"
        pattern: ファイル名パターン（省略時はモデルごとに既定）
        base_dir: 保存先ディレクトリ
    Returns:
        (ファイルパス, init_time) or (None, None)
    """
    model = model.upper()
    if pattern is None:
        pattern = GPV_PATTERNS.get(model, GPV_PATTERNS["GSM"])
    now = datetime.utcnow() + timedelta(hours=9)  # JST
    tried = []
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y = dt.strftime("%Y")
        m = dt.strftime("%m")
        d = dt.strftime("%d")
        for h in [18, 12, 6, 0]:  # 新しい順
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{y}/{m}/{d}/{fname}"
            out_dir = os.path.abspath(base_dir)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, fname)
            tried.append(url)
            try:
                urllib.request.urlretrieve(url, out_path)
                print(f"[OK] {model} GPVダウンロード: {out_path}")
                return out_path, datetime(dt.year, dt.month, dt.day, h)
            except Exception as e:
                print(f"[NG] {url.split('/')[-1]}: {e}")
    print(f"【ERROR】直近2日間で{model} GPVファイルが見つかりませんでした。")
    print("試行URL：")
    for t in tried:
        print(t)
    return None, None

# ===============================
# エイリアス関数で互換性も維持
# ===============================
def download_gsm_gpv(pattern=None, base_dir=BASE_DIR):
    """従来のGSM専用APIも提供"""
    return download_gpv(model="GSM", pattern=pattern, base_dir=base_dir)

def download_msm_gpv(pattern=None, base_dir=BASE_DIR):
    """MSM専用APIも同じ関数でラップ"""
    return download_gpv(model="MSM", pattern=pattern, base_dir=base_dir)

# ===============================
# grib2→NetCDF変換・そのまま流用可
# ===============================
def grib2_to_nc(grib2_path):
    """
    wgrib2によるgrib2→NetCDF変換
    """
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    if nc_path.exists():
        print(f"既にNetCDF変換済: {nc_path}")
        return nc_path
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[INFO] grib2→nc変換: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError("grib2→nc変換に失敗しました")
    print(f"[INFO] 変換後NetCDF: {nc_path}")
    return nc_path

# ---- テスト・手動実行時の例 ----
if __name__ == "__main__":
    # モデル切り替えも簡単！
    for model in ["GSM", "MSM"]:
        grib2_path, init_time = download_gpv(model=model)
        if grib2_path:
            nc_path = grib2_to_nc(grib2_path)
            print(f"取得→変換: {grib2_path} -> {nc_path}")
        else:
            print(f"{model} GPVが見つかりません")
