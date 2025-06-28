# module/utils/xr_utils.py
# ==============================================
# xarray Datasetリストの「共通部分のみ」抽出ユーティリティ
# 2025-06-12 by ChatGPT
# ----------------------------------------------
# 使い方:
#   from module.utils.xr_utils import align_datasets_common
#   aligned = align_datasets_common(ds_list)
#   ds_merged = xr.concat(aligned, dim="time", compat="override")
# ==============================================

import numpy as np
import xarray as xr

def align_datasets_common(ds_list, dims=('time', 'latitude', 'longitude')):
    """
    ds_list（xarray.Datasetのリスト）から、指定dimsの共通部分のみ抽出したリストを返す。
    例: GSM/秋田/局所/地上など格子点数や時刻が違う複数データを「完全一致部分」で揃えられる。
    """
    if len(ds_list) == 0:
        return []
    # 各次元の共通部分（intersection）を抽出
    common = {}
    for dim in dims:
        arrs = [ds[dim].values for ds in ds_list if dim in ds.sizes or dim in ds.coords]
        if not arrs:
            continue
        common[dim] = arrs[0]
        for arr in arrs[1:]:
            common[dim] = np.intersect1d(common[dim], arr)
        # 長さゼロはスキップ
        if len(common[dim]) == 0:
            raise ValueError(f"共通部分が空です: {dim}")
    # 共通部分だけでスライス
    ds_list_aligned = [ds.sel({dim: common[dim] for dim in common}) for ds in ds_list]
    return ds_list_aligned
