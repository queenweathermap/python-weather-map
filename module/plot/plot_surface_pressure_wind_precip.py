# ===============================================
# module/plot/plot_surface_pressure_wind_precip.py
# 地上海面更正気圧・風・降水量 描画モジュール
# plot_surface_pressure_and_wind_msm(ax, ds, step=0)
# -----------------------------------------------
# 2025-06-26 ChatGPT リファクタ・シグネチャ統一
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var_2d, get_lon_lat
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var

from module.plot.plot_utils import set_japanese_font, plot_no_data_japan_map
set_japanese_font()  # 日本語フォントを全描画で有効化


def get_lon_lat(ds):
    """
    ds（xarray.Dataset）から2次元格子の経度・緯度配列を生成
    """
    lon2d = get_var(ds, "longitude")
    lat2d = get_var(ds, "latitude")
    if lon2d is not None and lat2d is not None and lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)   # ←インデントを深く！
    return lon2d, lat2d


def plot_surface_pressure_and_wind_msm(ax, ds, step=None, **kwargs):
    """
    地上海面更正気圧・風・降水量（MSM）描画
    Parameters
    ----------
    ax : matplotlib.axes.Axes
        描画先
    ds : xarray.Dataset（stepでスライス済みを渡す）
        GRIB2等から読み込んだxarrayデータセット
    Returns
    -------
    None
    """
    lon2d, lat2d = get_lon_lat(ds)
    prmsl = get_var(ds, "PRMSL_meansealevel")
    u10 = get_var(ds, "UGRD_10maboveground")
    v10 = get_var(ds, "VGRD_10maboveground")
    precip = get_var(ds, "APCP_surface")
    skip = 5  # 風ベクトルの間引き間隔

    # ...以降は既存通り（描画処理）



    # 地図範囲・装飾
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 海面更正気圧（等圧線） ---
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
        cb.set_label("PA [mm]", fontsize=8)

    ax.set_title("Surface Pressure / Wind / Precipitation", fontsize=10, pad=10)
