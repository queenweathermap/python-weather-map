# ===============================================================
# module/utils/var_utils.py
# 気象変数取得＋2D保証ユーティリティ（xarray.Dataset対応/標準名エイリアス付き）
# 2025-06-29 ChatGPT
# ===============================================================

import numpy as np
import re

# --- 変数名エイリアス辞書（標準名: よくあるキー名リスト） ---
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

def get_var(ds, key):
    """
    xarray.Dataset から変数（DataArray）を取得（標準名・エイリアス対応）
    - ds: xarray.Dataset
    - key: 標準名 or よくある略号
    """
    if key in ds.variables:
        return ds[key]
    # エイリアス探索
    aliases = VAR_ALIASES.get(key, [])
    for alias in aliases:
        if alias in ds.variables:
            return ds[alias]
    # 小文字変換でも試す
    if key.lower() in ds.variables:
        return ds[key.lower()]
    return None

def get_var_2d(ds, var_name, level=None, time_idx=None, step_idx=None):
    """
    xarray.Dataset から指定変数・レベルの2D配列を抽出
    - ds: xarray.Dataset
    - var_name: 標準名（例: "TMP_700mb" など）
    - level: 気圧面hPa（例: 700）またはNone
    - time_idx, step_idx: スライス指定（不要ならNone）
    """
    arr = get_var(ds, var_name)
    if arr is None:
        raise ValueError(f"{var_name} が ds.variables に見つかりません")
    # レベル自動抽出（"TMP_700mb"→700など）
    if level is None:
        m = re.match(r"[A-Z]+_(\d+)mb", var_name)
        if m:
            level = int(m.group(1))
    if level is not None:
        # isobaricInhPa or level どちらかで抽出
        for lev_key in ["isobaricInhPa", "level"]:
            if lev_key in arr.dims or lev_key in arr.coords:
                arr = arr.sel({lev_key: level}, method="nearest")
    # 時間・ステップでスライス
    if (time_idx is not None) and ("time" in arr.dims):
        arr = arr.isel(time=time_idx)
    if (step_idx is not None) and ("step" in arr.dims):
        arr = arr.isel(step=step_idx)
    arr2d = arr.squeeze()
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}, dims={arr.dims}")
    return np.asarray(arr2d)

def get_lon_lat(ds):
    """
    xarray.Dataset/DataArray から2D緯度・経度配列取得（1Dならmeshgrid化）
    - ds: xarray.Dataset or DataArray
    """
    # よくあるケース両対応
    lon = get_var(ds, "longitude")
    lat = get_var(ds, "latitude")
    if lon is None or lat is None:
        raise ValueError("longitude/latitudeが取得できません")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の形状が不正")
    return lon2d, lat2d

__all__ = ["get_var", "get_var_2d", "get_lon_lat"]
