# scripts/gpv_downloader.py
# ===============================
# 気象庁GPV自動ダウンロード&GRIB2→NetCDF変換モジュール
# ===============================
import os, urllib.request, subprocess
from datetime import datetime, timedelta
from pathlib import Path

def download_gpv(pattern, base_dir, hours=[18,12,6,0], days=2):
    now = datetime.utcnow() + timedelta(hours=9)
    tried = []
    for day_offset in range(days):
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
        for h in hours:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{y}/{m}/{d}/{fname}"
            out_path = os.path.join(base_dir, fname)
            tried.append(url)
            try:
                urllib.request.urlretrieve(url, out_path)
                print(f"[OK] DL: {out_path}")
                return out_path, datetime(dt.year, dt.month, dt.day, h)
            except Exception as e:
                print(f"[NG] {fname}: {e}")
    print("DL失敗 試行URL:", *tried, sep="\n- ")
    return None, None

def grib2_to_nc(grib2_path):
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"wgrib2 {grib2_path} -netcdf {nc_path}"
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError("grib2→nc変換に失敗")
    return str(nc_path)
