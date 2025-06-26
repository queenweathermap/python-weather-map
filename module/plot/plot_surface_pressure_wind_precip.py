# ===============================================
# module/plot_surface_pressure_wind_precip.py
# 地上海面更正気圧・風・降水量 描画モジュール
# GSM/MSM両対応（引数 model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 日本語コメント多め。天気図プロジェクト向けの汎用・高機能地上天気図プロット関数です
# 利用例:
#   from module.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_surface_pressure_and_wind_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# ------------------------------------------------------
# xarray Dataset から経度・緯度の2次元格子を取得する関数
# ------------------------------------------------------
def get_lon_lat(ds):
    """
    ds（xarray.Dataset）から2次元格子の経度・緯度配列を生成
    """
    lon2d = get_var(ds, "longitude")
    lat2d = get_var(ds, "latitude")
    if lon2d is not None and lat2d is not None and lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# ------------------------------------------------------
# 地上天気図（気圧・風・降水量）描画本体
# ------------------------------------------------------
def plot_surface_pressure_and_wind(ax, ds, model="GSM", prop=None, skip=5):
    """
    地上海面更正気圧・風ベクトル・降水量を天気図として描画
    - ax: matplotlib axis（ccrs.PlateCarree() 必須）
    - ds: xarray.Dataset
    - model: "GSM" or "MSM" など
    - prop: フォントプロパティ（任意）
    - skip: 風ベクトルの間引き間隔
    """
    lon2d, lat2d = get_lon_lat(ds)
    prmsl = get_var(ds, "PRMSL_meansealevel")
    u10 = get_var(ds, "UGRD_10maboveground")
    v10 = get_var(ds, "VGRD_10maboveground")
    precip = get_var(ds, "APCP_surface")

    # 地図範囲・装飾
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 海面更正気圧（等圧線：細線/太線） ---
    if prmsl is not None:
        prmsl_hpa = prmsl / 100  # [hPa]
        levels_fine = np.arange(900, 1101, 1)
        cs = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_fine, colors='k', linewidths=0.6,
            transform=ccrs.PlateCarree()
        )
        levels_bold = np.arange(900, 1101, 4)
        cs_bold = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_bold, colors='k', linewidths=2.0,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(cs, fmt="%.0f", fontsize=6)
        label_texts = ax.clabel(cs_bold, fmt="%.0f", fontsize=8, colors='k')
        for txt in label_texts:
            txt.set_fontweight('bold')

        # H/Lマーク自動描画（最高/最低気圧）
        prmsl_max = maximum_filter(prmsl_hpa, size=5)
        prmsl_min = minimum_filter(prmsl_hpa, size=5)
        prmsl_flat = prmsl_hpa.flatten()
        hmax_indices = np.argpartition(prmsl_flat, -2)[-2:]
        hmin_indices = np.argpartition(prmsl_flat, 2)[:2]
        hmax_coords = np.unravel_index(hmax_indices, prmsl_hpa.shape)
        hmin_coords = np.unravel_index(hmin_indices, prmsl_hpa.shape)
        for j, i in zip(*hmax_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
        for j, i in zip(*hmin_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    # --- 10m風ベクトル ---
    if u10 is not None and v10 is not None:
        ax.quiver(
            lon2d[::skip, ::skip], lat2d[::skip, ::skip],
            u10[::skip, ::skip], v10[::skip, ::skip],
            transform=ccrs.PlateCarree(), scale=500, width=0.002, alpha=0.8
        )

    # --- 降水量（色塗り） ---
    if precip is not None:
        cf = ax.contourf(
            lon2d, lat2d, precip,
            levels=np.arange(0, 51, 5), cmap="Blues", alpha=0.4,
            transform=ccrs.PlateCarree()
        )
        cb = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
        cb.set_label("PA [mm]", fontsize=8, fontproperties=prop)

    # --- タイトル ---
    ax.set_title("surface_pressure_and_wind", fontsize=10, pad=10, fontproperties=prop)

# ------------------------------------------------------
# GSM/MSMラッパー関数
# ------------------------------------------------------
def plot_surface_pressure_and_wind_gsm(ax, ds, prop=None, skip=5):
    """GSM用ラッパー"""
    return plot_surface_pressure_and_wind(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_surface_pressure_and_wind_msm(ax, ds, prop=None, skip=5):
    """MSM用ラッパー"""
    return plot_surface_pressure_and_wind(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
