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

import numpy as np
import xarray as xr

def align_datasets_common(ds_list, dims=('time', 'latitude', 'longitude')):
    """
    ds_list（xarray.Datasetのリスト）から、指定dimsの共通部分のみ抽出したリストを返す。
    """
    # 各次元の共通部分
    common = {}
    for dim in dims:
        arrs = [ds[dim].values for ds in ds_list if dim in ds.dims or dim in ds.coords]
        common[dim] = arrs[0]
        for arr in arrs[1:]:
            common[dim] = np.intersect1d(common[dim], arr)
    ds_list_aligned = [ds.sel({dim: common[dim] for dim in dims}) for ds in ds_list]
    return ds_list_aligned
