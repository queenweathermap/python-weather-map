# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

# module/utils/var_utils.py
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
