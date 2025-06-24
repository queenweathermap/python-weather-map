# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa Dewpoint Depression + 500hPa Temperature Contour Plot Module
# Compatible with GSM/MSM (by wrapper function)
# -----------------------------------------------

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM"):
    """
    Draw 700hPa dewpoint depression (color) and 500hPa temperature contour.
    """
    lon2d, lat2d = get_lon_lat(ds)
    # --- 必要な変数を抽出 ---
    temp_500 = get_var(ds, "TMP_500mb")
    temp_700 = get_var(ds, "TMP_700mb")
    rh_700   = get_var(ds, "RH_700mb")
    
    # テスト用にValueErrorをコメントアウト
    # if temp_500 is None or temp_700 is None or rh_700 is None:
    #     raise ValueError("Required 700/500hPa variables missing.")

    # --- ケルビン→摂氏変換 ---
    if temp_500 is not None:
        temp_500_c = temp_500 - 273.15
    else:
        temp_500_c = None
    if temp_700 is not None:
        temp_700_c = temp_700 - 273.15
    else:
        temp_700_c = None

    # --- 700hPa湿数（Dewpoint Depression） ---
    if rh_700 is not None and temp_700_c is not None:
        dewpoint_700 = temp_700_c - (100 - rh_700) / 5
        dindex_700 = temp_700_c - dewpoint_700
        # --- 湿数のカラーマップ設定 ---
        colors = [
            (0.0, "#006400"),
            (0.25, "#32cd32"),
            (0.5, "#adff2f"),
            (0.75, "#ffff66"),
            (1.0, "#ffd700"),
        ]
        cmap = LinearSegmentedColormap.from_list("drywet", colors)
        cf = ax.contourf(
            lon2d, lat2d, dindex_700,
            levels=np.linspace(0, 30, 13),
            cmap=cmap, extend="max", alpha=0.8,
            transform=ccrs.PlateCarree()
        )
        cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
        cbar.set_label("700hPa Dewpoint Depression [°C]", fontsize=8)
    else:
        # --- rh_700がない場合は700hPa気温だけ背景に描く（もしくは何もしない）---
        if temp_700_c is not None:
            cf = ax.contourf(
                lon2d, lat2d, temp_700_c,
                levels=np.arange(-40, 20, 2),
                cmap="coolwarm", alpha=0.5, transform=ccrs.PlateCarree()
            )
            cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
            cbar.set_label("700hPa Temperature [°C]", fontsize=8)

    # --- 地図範囲・海岸線 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 500hPa等温線 ---
    if temp_500_c is not None:
        cs = ax.contour(
            lon2d, lat2d, temp_500_c,
            levels=np.arange(-60, 0, 2),
            colors='navy', linewidths=0.7,
            linestyles='solid', transform=ccrs.PlateCarree(),
            zorder=10
        )
        ax.clabel(cs, fmt="%d", fontsize=6)
    ax.set_title("700hPa D-index/Temp & 500hPa Temp (TEST ver)", fontsize=10, pad=10)

def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM")

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
