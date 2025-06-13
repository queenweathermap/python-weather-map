# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================


import numpy as np

def get_var(ds, var):
    """
    xarray.Datasetやdict, DataFrame等から安全にNumPy配列を取得
    無ければNoneを返す
    """
    if isinstance(ds, dict):
        x = ds.get(var, None)
    else:
        x = ds[var] if var in getattr(ds, 'variables', {}) else None
    if x is None:
        return None
    return np.array(x)  # asarrayでも可だがarrayの方が階層崩壊で止まりやすい
