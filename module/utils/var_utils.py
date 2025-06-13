# ==========================================
# var_utils.py
# xarray変数取得 共通ユーティリティ
# ==========================================
import numpy as np

def get_var(ds, var):
    if var in ds:
        x = ds[var]
        # DataArrayやnumpy配列両対応
        return np.asarray(x) if hasattr(x, "__array__") else x
    return None
