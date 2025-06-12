# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa湿数＋500hPa等温線描画モジュール
# GSM/MSM両対応（ラッパー関数で分岐）
# -----------------------------------------------
# 利用例:
#   from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_700hpa_dindex_500hpa_temp_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap

def get_lon_lat(ds):
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM"):
    lon2d, lat2d = get_lon_lat(ds)
    # --- モデル分岐 ---
    temp_500 = ds["TMP_500mb"].values - 273.15
    temp_700 = ds["TMP_700mb"].values - 273.15
    rh_700   = ds["RH_700mb"].values
    # 湿数計算
    dewpoint_700 = temp_700 - (100 - rh_700) / 5
    dindex_700 = temp_700 - dewpoint_700

    # カラーマップ
    colors = [
        (0.0, "#006400"),
        (0.25, "#32cd32"),
        (0.5, "#adff2f"),
        (0.75, "#ffff66"),
        (1.0, "#ffd700"),
    ]
    cmap = LinearSegmentedColormap.from_list("drywet", colors)

    # 地図・海岸線
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 700hPa湿数
    cf = ax.contourf(
        lon2d, lat2d, dindex_700,
        levels=np.linspace(0, 30, 13),
        cmap=cmap, extend="max", alpha=0.8,
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa湿数 [℃]", fontsize=8)

    # 500hPa等温線
    cs = ax.contour(
        lon2d, lat2d, temp_500,
        levels=np.arange(-60, 0, 2),
        colors='navy', linewidths=0.7,
        linestyles='solid', transform=ccrs.PlateCarree(),
        zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)
    ax.set_title("500hPa温度・700hPa湿数", fontsize=10, pad=10)

# ======= ラッパー関数 =======
def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM")

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="MSM")
# ===============================================
# END OF FILE
# ===============================================
