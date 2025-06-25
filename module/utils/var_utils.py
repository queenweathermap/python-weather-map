# ===============================================
# module/utils/var_utils.py
# 変数取得＋2D保証（標準名マッピング付き）完全最新版
# ===============================================

import numpy as np
import re

def get_var(ds, var):
    """
    ds: xarray.Dataset
    var: 標準名（例：TMP_850mb, UGRD_850mb など）
    GRIB2/JMA GPVの温度・風・湿度等は "t", "u", "v", "r", "gh" で格納されている
    """
    # まず完全一致
    if var in ds.variables:
        return ds[var]
    # "TMP_850mb" → "t" + isobaricInhPa=850 などに自動分解
    m = re.match(r"([A-Z]+)_(\d+)mb", var)
    if m:
        short, lvl = m.groups()
        shortname_map = {
            "TMP": "t", "UGRD": "u", "VGRD": "v", "VVEL": "w", "RH": "r", "HGT": "gh"
        }
        shortname = shortname_map.get(short)
        if shortname and shortname in ds.variables:
            return ds[shortname]

# --- 標準名エイリアス辞書 ---
VAR_ALIASES = {
    # 標準名         cfgrib名   NetCDF名 等 (追加はここだけ！)
    "TMP_500mb":    ["t@500", "t_500hPa", "temperature_500"],
    "TMP_700mb":    ["t@700", "t_700hPa"],
    "TMP_850mb":    ["t@850", "t_850hPa"],
    "UGRD_850mb":   ["u@850", "u_850hPa"],
    "VGRD_850mb":   ["v@850", "v_850hPa"],
    "RH_700mb":     ["r@700", "rh_700hPa"],
    "VVEL_700mb":   ["w@700", "w_700hPa"],
    "HGT_500mb":    ["gh@500", "z_500hPa"],
    # ...他も同様に追加
    "longitude":    ["lon", "longitude"],
    "latitude":     ["lat", "latitude"],
}

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

def get_var_2d(ds, var_name, level=None, time_idx=0):
    """
    - ds: xarray.Dataset
    - var_name: 標準名
    - level: 取得したい気圧面（例 850, 700）
    - time_idx: 取得したい時刻index
    """
    da = get_var(ds, var_name)
    print(f"[DEBUG] get_var_2d({var_name}) got {da}")
    if da is None:
        return None
    print(f"[DEBUG] get_var({var_name}) →", type(da), "dims:", getattr(da, "dims", None))
    if da is None:
        print(f"[WARN] {var_name}: get_var returns None")
        return None
    arr = da
    # 気圧面名抽出（例 TMP_850mb → 850）
    if level is None:
        m = re.match(r"[A-Z]+_(\d+)mb", var_name)
        if m:
            level = int(m.group(1))
    print("==== isobaricInhPa ====")
    if "isobaricInhPa" in arr.dims:
        print(f"[DEBUG] {var_name}: isobaricInhPa:", arr.coords["isobaricInhPa"].values)
        print(ds.coords["isobaricInhPa"].values)
    else:
        print("No isobaricInhPa in ds.coords")


    # --- 時間・気圧面をもつ多次元配列なら正しくスライス ---
    if "time" in arr.dims and "isobaricInhPa" in arr.dims:
        arr = arr.isel(time=time_idx)
        # レベル選択は「最近傍」で
        level_vals = arr.coords["isobaricInhPa"].values
        ilevel = np.abs(level_vals - level).argmin()
        arr = arr.isel(isobaricInhPa=ilevel)
    elif "time" in arr.dims:
        arr = arr.isel(time=time_idx)
    elif "isobaricInhPa" in arr.dims:
        level_vals = arr.coords["isobaricInhPa"].values
        ilevel = np.abs(level_vals - level).argmin()
        arr = arr.isel(isobaricInhPa=ilevel)
    # --- 必ず2Dになるまでsqueeze ---
    arr2d = np.asarray(arr.squeeze())
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}, dims={arr.dims}")
    return arr2d

__all__ = ["get_var", "get_var_2d"]
