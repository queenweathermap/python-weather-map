# module/utils/var_utils.py
# ===============================================
# 変数取得＋2D保証（標準名マッピング付き）完全最新版
# ===============================================

import numpy as np
import re
import xarray as xr
import cfgrib

# --- 標準名エイリアス辞書 ---
VAR_ALIASES = {
    "TMP_500mb":    ["t", "t@500", "t_500hPa", "temperature_500"],
    "TMP_700mb":    ["t", "t@700", "t_700hPa"],
    "TMP_850mb":    ["t", "t@850", "t_850hPa"],
    "UGRD_850mb":   ["u", "u@850", "u_850hPa"],
    "VGRD_850mb":   ["v", "v@850", "v_850hPa"],
    "RH_700mb":     ["r", "r@700", "rh_700hPa"],
    "VVEL_700mb":   ["w", "w@700", "w_700hPa"],
    "HGT_500mb":    ["gh", "gh@500", "z_500hPa"],
    "longitude":    ["lon", "longitude"],
    "latitude":     ["lat", "latitude"],
}

def open_all_subdatasets(file_path):
    """cfgrib.open_datasetsで全サブセット取得"""
    return cfgrib.open_datasets(file_path)

def select_subdataset_by_var(datasets, var_name):
    """複数サブセットから、指定変数を含むサブセットを返す"""
    for ds in datasets:
        if var_name in ds.data_vars:
            return ds
    # エイリアスも探索
    for ds in datasets:
        for aliases in VAR_ALIASES.get(var_name, []):
            if aliases in ds.data_vars:
                return ds
    raise ValueError(f"{var_name} が見つかりません")

def get_var(ds, key):
    # 標準名・エイリアスに対応
    if key in ds.variables:
        return ds[key]
    aliases = VAR_ALIASES.get(key, [])
    for alias in aliases:
        if alias in ds.variables:
            return ds[alias]
    if key.lower() in ds.variables:
        return ds[key.lower()]
    return None

def get_var_2d_from_ds(ds, var_name, level=None, time_idx=None, step_idx=None):
    """
    ds: xarray.Dataset
    var_name: 標準名（TMP_850mbなど）
    level: 取得したい気圧面（例 850, 700）
    time_idx, step_idx: スライス指定（必要に応じて）
    """
    da = get_var(ds, var_name)
    if da is None:
        raise ValueError(f"{var_name} が ds.variables に見つかりません")
    arr = da
    # レベル抽出
    if level is None:
        m = re.match(r"[A-Z]+_(\d+)mb", var_name)
        if m:
            level = int(m.group(1))
    if level is not None:
        for lev_key in ["isobaricInhPa", "level"]:
            if lev_key in arr.dims or lev_key in arr.coords:
                arr = arr.sel({lev_key: level}, method="nearest")
    # 時間・ステップスライス
    if (time_idx is not None) and ("time" in arr.dims):
        arr = arr.isel(time=time_idx)
    if (step_idx is not None) and ("step" in arr.dims):
        arr = arr.isel(step=step_idx)
    arr2d = arr.squeeze()
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}, dims={arr.dims}")
    return arr2d

def get_var_2d(file_path, var_name, level=None, time_idx=None, step_idx=None):
    """ファイルパス→自動サブセット抽出→2D"""
    datasets = open_all_subdatasets(file_path)
    ds = select_subdataset_by_var(datasets, var_name)
    return get_var_2d_from_ds(ds, var_name, level, time_idx, step_idx)

def get_lon_lat(ds):
    """
    xarray.Dataset/DataArrayから2D経度・緯度配列を取得
    （1Dならmeshgrid化、2Dならそのまま）
    """
    lon = ds["longitude"] if "longitude" in ds else ds.coords["longitude"]
    lat = ds["latitude"] if "latitude" in ds else ds.coords["latitude"]
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の形状が不正")
    return lon2d, lat2d


__all__ = ["get_var", "get_var_2d", "get_var_2d_from_ds"]
