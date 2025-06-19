# ===============================================
# module/plot_975hpa_temp_wind_dindex.py
# 975hPa Temperature, Wind, and Dewpoint Depression Plot Module（全国MSM用）
# -----------------------------------------------
# 日本語コメント多数：975hPaの気温・風・湿数（湿数=気温-露点温度）を地図上に可視化します
# 利用例:
#   from module.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex_msm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_975hpa_temp_wind_dindex_msm(ax, ds)
#   plt.show()
# -----------------------------------------------
# モデル引数"model"は将来的な拡張性を考慮した設計
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# Datasetから緯度経度2D配列を取得（meshgrid変換も自動対応）
# -------------------------------------------------
def get_lon_lat(ds):
    """
    Converts xarray Dataset lon/lat to 2D meshgrid arrays.
    日本語：1次元格子でも2次元化して返す
    """
    lon2d = get_var(ds, "longitude")
    lat2d = get_var(ds, "latitude")
    if lon2d is not None and lat2d is not None and lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# 975hPa温度・風・湿数を描画するメイン関数
# -------------------------------------------------
def plot_975hpa_temp_wind_dindex(ax, ds, model="MSM", prop=None, skip=5):
    """
    Draws 975hPa temperature (contour), wind (vector), and dewpoint depression (color filled).
    日本語：975hPaの気温・風（ベクトル）・湿数（色塗り）を同時に描画
    - ax: PlateCarree axes
    - ds: xarray.Dataset
    - model: "MSM"推奨（将来的な拡張用）
    - prop: フォント設定
    - skip: 風ベクトルの間引き間隔
    """
    # --- 2次元緯度経度配列 ---
    lon2d, lat2d = get_lon_lat(ds)
    
    # --- 必要な物理量の取得 ---
    temp = get_var(ds, "TMP_975mb")     # 975hPa気温（K）
    u = get_var(ds, "UGRD_975mb")       # 975hPa東西風（m/s）
    v = get_var(ds, "VGRD_975mb")       # 975hPa南北風（m/s）
    rh = get_var(ds, "RH_975mb")        # 975hPa相対湿度（%）

    # --- 欠損データチェック ---
    if temp is None or u is None or v is None or rh is None:
        raise ValueError("Required 975hPa variables are missing.")

    # --- K → ℃変換 ---
    temp_c = temp - 273.15

    # --- 露点温度（近似式）---
    dewpoint = temp_c - (100 - rh) / 5.0

    # --- 湿数（気温-露点温度）---
    dindex = temp_c - dewpoint

    # --- 地図基本設定 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 975hPa気温 等値線 ---
    cs_temp = ax.contour(
        lon2d, lat2d, temp_c, levels=np.arange(-20, 36, 2), colors="k",
        linewidths=0.7, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs_temp, fontsize=6)

    # --- 975hPa湿数 塗り分け ---
    cf = ax.contourf(
        lon2d, lat2d, dindex, levels=np.linspace(0, 30, 13),
        cmap="Greens", alpha=0.6, transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("975hPa Dewpoint Depression [℃]", fontsize=8)

    # --- 975hPa風ベクトル ---
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )

    ax.set_title("975hPa Temperature / Wind / Dewpoint Depression", fontsize=10, pad=10, fontproperties=prop)

# -------------------------------------------------
# MSMラッパー関数
# -------------------------------------------------
def plot_975hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    """
    全国MSM（975hPa）のためのラッパー関数
    """
    return plot_975hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
