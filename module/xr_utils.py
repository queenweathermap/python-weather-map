# module/xr_utils.py
# ==============================================
# xarray Datasetリストの「共通部分のみ」抽出ユーティリティ
# 2025-06-12 by ChatGPT
# ----------------------------------------------
# 使い方:
#   from module.xr_utils import align_datasets_common
#   aligned = align_datasets_common(ds_list)
#   ds_merged = xr.concat(aligned, dim="time", compat="override")
# ==============================================

import xarray as xr

def align_datasets_common(ds_list, dims=("time", "latitude", "longitude")):
    """
    複数xarray.Datasetの指定次元・変数の「共通部分」だけでリストを返す。
    - ds_list: [xr.Dataset, xr.Dataset, ...]
    - dims:    共通部分を取りたい次元（デフォルト：time, latitude, longitude）
    """
    # 1. 各次元の共通値を列挙
    common_coords = {}
    for dim in dims:
        values = set(ds_list[0][dim].values)
        for ds in ds_list[1:]:
            values &= set(ds[dim].values)
        common_coords[dim] = sorted(list(values))
    # 2. 共通変数名を取得
    common_vars = set(ds_list[0].data_vars)
    for ds in ds_list[1:]:
        common_vars &= set(ds.data_vars)
    common_vars = list(common_vars)

    # 3. 全データセットを「共通部分だけ」でselし、変数も限定
    ds_list_aligned = [
        ds[common_vars].sel(**{dim: common_coords[dim] for dim in dims})
        for ds in ds_list
    ]
    return ds_list_aligned
