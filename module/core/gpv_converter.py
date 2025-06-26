# module/core/gpv_converter.py
# ===============================================
# GRIB2ファイル⇔NetCDF変換（wgrib2ラッパ）
# 2025-06-27 by ChatGPT
# ===============================================
import os
import subprocess

def grib2_to_netcdf(grib2_path, out_nc_path):
    """GRIB2→NetCDF変換（wgrib2必須）"""
    cmd = ["wgrib2", grib2_path, "-netcdf", out_nc_path]
    try:
        subprocess.run(cmd, check=True)
        return out_nc_path
    except Exception as e:
        print(f"[ERROR] GRIB2→NetCDF変換失敗: {e}")
        return None

def netcdf_exists(nc_path):
    """NetCDFファイルの存在確認"""
    return os.path.exists(nc_path)
