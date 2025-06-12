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
    """
    700hPa湿数＋500hPa等温線の描画（GSM/MSM両対応）

    湿数: 700hPa気温と700hPa相対湿度から算出（乾燥=黄色、湿潤=緑、グラデ）
    500hPa等温線: 紺色
    """
    lon2d, lat2d = get_lon_lat(ds)

    # モデル分岐
    if model == "GSM":
        temp_500 = ds["TMP_500mb"].values - 273.15
        temp_700 = ds["TMP_700mb"].values - 273.15
        rh_700   = ds["RH_700mb"].values
    elif model == "MSM":
        temp_500 = ds["TMP_500mb"].values - 273.15
        temp_700 = ds["TMP_700mb"].values - 273.15
        rh_700   = ds["RH_700mb"].values
    else:
        raise ValueError("model must be 'GSM' or 'MSM'")

    dewpoint_700 = temp_700 - (100 - rh_700) / 5
    dindex_700 = temp_700 - dewpoint_700

    colors = [
        (0.0, "#006400"),
        (0.25, "#32cd32"),
        (0.5, "#adff2f"),
        (0.75, "#ffff66"),
        (1.0, "#ffd700"),
    ]
    cmap = LinearSegmentedColormap.from_list("drywet", colors)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cf = ax.contourf(
        lon2d, lat2d, dindex_700,
        levels=np.linspace(0, 30, 13),
        cmap=cmap, extend="max",
        alpha=0.8,
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa湿数 [℃]", fontsize=8)
    ticks = cbar.ax.get_yticks()
    labels = [f"{int(l)}" for l in ticks]
    if len(labels) >= 2:
        labels[-1] = f"{labels[-2]}+"
    cbar.set_ticks(ticks)
    cbar.set_ticklabels(labels)

    cs = ax.contour(
        lon2d, lat2d, temp_500,
        levels=np.arange(-60, 0, 2),
        colors='navy',
        linewidths=0.7,
        linestyles='solid',
        transform=ccrs.PlateCarree(),
        zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)
    ax.set_title("500hPa温度・700hPa湿数", fontsize=10, pad=10)

# ======= ラッパー関数（import用） =======
def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM")

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
