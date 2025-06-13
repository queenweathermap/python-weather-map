# ==========================================
# var_utils.py
# xarray変数取得 共通ユーティリティ
# ==========================================
import numpy as np

def get_var(ds, var):
    """ds[var]が存在すればnp.asarrayで返す（なければNone）"""
    return np.asarray(ds[var]) if var in ds else None
