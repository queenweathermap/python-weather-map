# module/utils/var_utils.py
# ==========================================
# # xarray変数取得 共通ユーティリティ
# ==========================================

def get_var(ds, var):
    """
    xarray.Dataset/Dictに対応し、安全にnumpy配列へ。
    存在しなければNone。
    """
    if isinstance(ds, dict):
        x = ds.get(var, None)
    else:
        x = ds[var] if var in ds.variables else None
    if x is None:
        return None
    return np.array(x)  # asarrayよりarrayの方が階層崩壊でエラー出にくい
