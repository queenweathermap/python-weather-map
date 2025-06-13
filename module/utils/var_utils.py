# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

import numpy as np
import xarray as xr

def get_var(ds, var):
    """
    xarray.Datasetやdict, DataFrame等から安全にNumPy配列を取得
    無ければNoneを返す
    """
    if isinstance(ds, dict):
        x = ds.get(var, None)
    else:
        # dsはxarray.Dataset前提
        if hasattr(ds, 'variables') and var in ds.variables:
            x = ds[var]
        elif hasattr(ds, '__contains__') and var in ds:
            x = ds[var]
        else:
            x = None
    if x is None:
        return None

    # xarray.DataArray の場合は .data を使う
    if isinstance(x, xr.DataArray):
        return np.asarray(x.data)
    # それ以外（普通の配列、Pandas、数値）もOK
    return np.asarray(x)
