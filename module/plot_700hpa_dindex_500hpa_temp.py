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
    700hPa湿数＋500hPa等温線描画（GSM/MSM両対応）
    """
    lon2d, lat2d = get_lon_lat(ds)
    # 各変数取得
    temp_500 = get_var(ds, "TMP_500mb")
    temp_700 = get_var(ds, "TMP_700mb")
    rh_700   = get_var(ds, "RH_700mb")
    if temp_500 is None or temp_700 is None or rh_700 is None:
        raise ValueError("必要な700/500hPa変数が含まれていません")
    temp_500_c = temp_500 - 273.15
    temp_700_c = temp_700 - 273.15

    # 湿数計算
    dewpoint_700 = temp_700_c - (100 - rh_700) / 5
    dindex_700 = temp_700_c - dewpoint_700

    # カラーマップ（黄緑系）
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
        lon2d, lat2d, temp_500_c,
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
