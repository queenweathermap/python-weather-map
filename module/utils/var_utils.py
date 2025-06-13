# ==========================================
# var_utils.py
# xarray変数取得 共通ユーティリティ
# ==========================================
import numpy as np

def get_var(ds, var):
    if isinstance(ds, dict):
        x = ds.get(var, None)
    else:
        x = ds[var] if var in ds.variables else None
    if x is None:
        return None
    try:
        return np.asarray(x)
    except Exception:
        return x
