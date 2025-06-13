# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

import numpy as np
import xarray as xr

def get_var(ds, var):
    """
    dsから指定変数をNumPy配列で安全に取得
    """
    x = ds.get(var, None) if isinstance(ds, dict) else (ds[var] if var in ds else None)
    if x is None:
        return None
    # ここで明示的に計算しきる
    if hasattr(x, "load"):
        x = x.load()
    if hasattr(x, "values"):
        return np.array(x.values)   # .values属性でNumPy配列として受け取る
    return np.array(x)
