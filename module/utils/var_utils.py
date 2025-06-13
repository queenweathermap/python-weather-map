# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

import numpy as np
import xarray as xr


def get_var(ds, var):
    """
    ds（xarray.Dataset等）から指定変数をNumPy配列で取得
    無ければNone
    """
    # dict形式にもxarrayにも対応
    x = ds.get(var, None) if isinstance(ds, dict) else (ds[var] if var in ds else None)
    if x is None:
        return None
    # xarray.DataArrayなら .values/.data なしでも np.asarray で全部配列化される
    return np.asarray(x)
