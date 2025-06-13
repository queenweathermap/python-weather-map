# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

import numpy as np
import xarray as xr

def get_var(ds, var):
    """
    dsから指定変数を安全にNumPy配列で取得
    - xarray.DataArray → .to_numpy()
    - ndarray → そのまま
    - list/float/int → np.array化
    """
    # dict形式 or Dataset
    x = ds.get(var, None) if isinstance(ds, dict) else (ds[var] if var in ds else None)
    if x is None:
        return None
    if hasattr(x, "to_numpy"):   # xarray.DataArray系
        return x.to_numpy()
    return np.array(x)

