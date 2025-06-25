# ===============================================
# module/utils/var_utils.py
# 変数取得＋2D保証（標準名マッピング付き）完全最新版
# ===============================================

import numpy as np
import re

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
        print(f"[WARN] get_var_2d({var_name}) -> None")
        return None
    print(f"[DEBUG] get_var({var_name}) →", type(da), "dims:", getattr(da, "dims", None))
    arr = da

    # 気圧面名抽出（例 TMP_850mb → 850）
    if level is None:
        m = re.match(r"[A-Z]+_(\d+)mb", var_name)
        if m:
            level = int(m.group(1))

    # --- 多次元配列のスライス処理 ---
    # もし isobaricInhPa があるなら level 指定でスライス
    if "isobaricInhPa" in arr.dims:
        if level is not None:
            level_vals = arr.coords["isobaricInhPa"].values
            ilevel = np.abs(level_vals - level).argmin()
            arr = arr.isel(isobaricInhPa=ilevel)
    # 時間次元もある場合は time_idxでスライス
    if "time" in arr.dims:
        arr = arr.isel(time=time_idx)

    # --- 必ず2Dになるまでsqueeze ---
    arr2d = np.asarray(arr.squeeze())
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}, dims={arr.dims}")
    return arr2d

__all__ = ["get_var", "get_var_2d"]
