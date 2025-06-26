# module/core/gpv_data_loader.py
# ===============================================
# GPVデータ読み込み（NetCDF/GRIB2→xarray.Dataset）
# NetCDFやxarrayローダー
# 2025-06-27 by ChatGPT　
# ===============================================
import xarray as xr

def load_dataset(nc_path):
    """NetCDF/xarrayデータセット読込"""
    try:
        return xr.open_dataset(nc_path)
    except Exception as e:
        print(f"[ERROR] NetCDF読み込み失敗: {e}")
        return None

def load_grib2(grib2_path, engine="cfgrib", filter_by_keys=None):
    """GRIB2直接読込（xarray+cfgrib）"""
    try:
        return xr.open_dataset(grib2_path, engine=engine, filter_by_keys=filter_by_keys)
    except Exception as e:
        print(f"[ERROR] GRIB2読み込み失敗: {e}")
        return None

