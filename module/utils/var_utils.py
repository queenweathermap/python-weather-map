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

def get_var(ds, key):
    # あなたの既存実装でOK（VAR_ALIASESも使ってね）
    # 例: ds[key] かエイリアス
    return ds[key] if key in ds.variables else None
    

# 既存のVAR_ALIASES & get_var ここにある想定
def get_var_2d(
    ds, key, level=None, time_idx=0, step_idx=0, ensemble_idx=0, **kwargs
):
    """
    dsからkeyを抽出し、「残った多次元軸は全部1つに固定」して2Dで返す。
    - ds: xarray.Dataset
    - key: 変数名
    - level: pressure level, e.g. 850
    - time_idx, step_idx, ensemble_idx: 指定軸のindex
    - kwargs: 追加の.isel/.sel用
    """
    arr = get_var(ds, key)
    if arr is None:
        return None

    # 柔軟に全次元を2Dになるまで落とす
    # よくある「代表的な軸」だけ特別扱いでindex指定
    for dim, idx in [("time", time_idx), ("step", step_idx), ("ensemble", ensemble_idx)]:
        if dim in arr.dims and arr.sizes[dim] > 1:
            arr = arr.isel({dim: idx})
    # isobaricInhPa, level, pressure のどれかに対応
    if level is not None:
        for lev_name in ["isobaricInhPa", "level", "pressure"]:
            if lev_name in arr.dims:
                arr = arr.sel({lev_name: level}, method="nearest")
    # 他に未指定の次元が残っていたら、先頭indexでスライス（順次2Dになるまで繰り返す）
    while arr.ndim > 2:
        arr = arr.isel({arr.dims[0]: 0})
    arr2d = np.asarray(arr.squeeze())
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}, dims={getattr(arr, 'dims', None)}")
    return arr2d
    

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


def get_var_2d(ds, var_name, level=None, time_idx=0):
    """
    - ds: xarray.Dataset
    - var_name: 例 "TMP_850mb"
    - level: 気圧面（hPa）例: 850
    - time_idx: 何番目の時刻か
    """
    da = get_var(ds, var_name)
    if da is None:
        return None
    arr = da
    # 時間・気圧面を持つ場合、スライス
    if "time" in da.dims and "isobaricInhPa" in da.dims:
        level_vals = da.coords["isobaricInhPa"].values
        # もっとも近いレベルを取得
        ilevel = np.abs(level_vals - level).argmin()
        arr = da.isel(time=time_idx, isobaricInhPa=ilevel)
    elif "time" in da.dims:
        arr = da.isel(time=time_idx)
    elif "isobaricInhPa" in da.dims:
        level_vals = da.coords["isobaricInhPa"].values
        ilevel = np.abs(level_vals - level).argmin()
        arr = da.isel(isobaricInhPa=ilevel)
    # 最後に2Dであることを保証
    arr2d = np.asarray(arr)
    if arr2d.ndim != 2:
        raise ValueError(f"Output is not 2D: shape={arr2d.shape}")
    return arr2d

