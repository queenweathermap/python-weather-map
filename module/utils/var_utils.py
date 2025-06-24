# ===============================================
# module/utils/var_utils.py
# 変数取得＋2D保証（標準名マッピング付き）
# ===============================================

import numpy as np


# --- 変数名マッピング辞書 ---
VAR_ALIASES = {
    # 標準名         cfgrib名   NetCDF名 等 (追加はここだけ！)
    "TMP_500mb":    ["t@500", "t_500hPa", "temperature_500"],
    "TMP_700mb":    ["t@700", "t_700hPa"],
    "TMP_850mb":    ["t@850", "t_850hPa"],
    "UGRD_850mb":   ["u@850", "u_850hPa"],
    "VGRD_850mb":   ["v@850", "v_850hPa"],
    "RH_850mb":     ["r@850", "rh_850hPa"],
    "VVEL_700mb":   ["w@700", "w_700hPa"],
    "HGT_500mb":    ["gh@500", "z_500hPa"],
    # ...他も同様に登録
    "longitude":    ["lon", "longitude"],
    "latitude":     ["lat", "latitude"],
}


# 既存のVAR_ALIASES & get_var ここにある想定

def get_var_2d(ds, key, level=None, time_idx=0):
    """
    xarray.Datasetから key/level/time_idxで2D(lat, lon)配列を取得
    - ds: xarray.Dataset
    - key: 標準変数名（例: "TMP_850mb"）
    - level: 指定気圧面（整数hPa、例: 500, 700 など。不要ならNone）
    - time_idx: 何番目の時刻か（0=先頭, 1=2番目…）
    """
    var = get_var(ds, key)
    if var is None:
        return None  # 変数なければNone
    arr = var
    # 時刻次元
    if "time" in arr.dims:
        arr = arr.isel(time=time_idx)
    # 気圧面次元
    if level is not None:
        # cfgribは isobaricInhPa, NetCDFはlev等 → 近いものを吸収
        for lev_dim in ["isobaricInhPa", "level", "lev"]:
            if lev_dim in arr.dims:
                arr = arr.sel({lev_dim: level}, method="nearest")
    # 緯度経度のみ残す
    arr_np = arr.values
    # 万一3Dや1D等の事故対応
    if arr_np.ndim == 3:
        arr_np = arr_np[0]
    elif arr_np.ndim == 1:
        # lat or lonだけ→meshgrid化推奨
        pass
    return arr_np  # shape=(lat, lon)



def get_var(ds, key):
    """多様な命名にも対応してxarray.Datasetから安全に取得"""
    # 直接
    if key in ds.variables:
        return ds[key]
    # 別名で
    aliases = VAR_ALIASES.get(key, [])
    for alias in aliases:
        if alias in ds.variables:
            return ds[alias]
    # 小文字も試す
    if key.lower() in ds.variables:
        return ds[key.lower()]
    return None

__all__ = ["get_var"]


def get_var(ds, var):
    """
    ds: xarray.Dataset (cfgrib: JMA GPV) or dict-like
    var: 標準名（例：TMP_850mb, UGRD_850mb...）
    cfgrib/NetCDF両対応
    """
    # cfgrib短縮名・レベル自動対応
    level_map = {
        "1000mb": 1000, "975mb": 975, "950mb": 950, "925mb": 925,
        "900mb": 900, "850mb": 850, "800mb": 800, "700mb": 700,
        "600mb": 600, "500mb": 500, "400mb": 400, "300mb": 300,
        "250mb": 250, "200mb": 200, "150mb": 150, "100mb": 100,
    }
    cfgrib_map = {
        "TMP": "t", "UGRD": "u", "VGRD": "v", "VVEL": "w", "RH": "r",
        "HGT": "gh", "PRMSL": "prmsl", # etc. 必要に応じ追加
    }
    # 標準名のパターン TMP_850mb などを分解
    import re
    m = re.match(r"([A-Z]+)_(\d+mb)", var)
    if m:
        key, lvl = m.groups()
        lvlv = level_map.get(lvl)
        short = cfgrib_map.get(key)
        if short and "isobaricInhPa" in ds.variables:
            # cfgrib変数
            try:
                return ds[short].sel(isobaricInhPa=lvlv)
            except Exception:
                return None
    # サーフェス・地上系
    surf_map = {
        "UGRD_10m": ("u10", None), "VGRD_10m": ("v10", None),
        "PRMSL": ("prmsl", None),
        # 他もあれば追加
    }
    if var in surf_map:
        short, _ = surf_map[var]
        if short in ds.variables:
            return ds[short]
    # 旧NetCDF名（wgrib2→NetCDF等）直接
    if var in ds.variables:
        return ds[var]
    return None
