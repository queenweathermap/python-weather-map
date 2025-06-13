# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

import numpy as np
import xarray as xr

def get_var(ds, var):
    """
    xarray DataSet/DataArrayから変数を安全にNumPy配列で取得
    """
    # 1. 存在確認
    if isinstance(ds, dict):
        x = ds.get(var, None)
    elif var in ds:
        x = ds[var]
    else:
        return None

    # 2. xarray.DataArrayなら、データを一度list経由で明示展開→np.array化（バグ潰し！）
    try:
        return np.array(list(x.values.ravel())).reshape(x.shape)
    except Exception:
        pass

    # 3. だめなら list→np.array
    try:
        return np.array(list(x.ravel())).reshape(x.shape)
    except Exception:
        pass

    # 4. 最後は生配列
    try:
        return np.array(x)
    except Exception:
        return None
