# ===============================================
# module/plot/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa Temperature & Wind + 700hPa Vertical Velocity
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
    lon = get_var(ds, "longitude")
    lat = get_var(ds, "latitude")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の形状が不正")
    return lon2d, lat2d

def plot_850hpa_temp_wind_700hpa_w(ax, ds, step=None, **kwargs):
    """
    850hPa気温・風・700hPa鉛直流
    ax: PlateCarree axes, ds: dict（stepで時系列スライス）
    """
    # 必ず引数dsからアクセス
    temp_850 = ds["t_850"]
    u_850 = ds["u_850"]
    v_850 = ds["v_850"]
    w_700 = ds["w_700"]
    
    # step次元があればスライス
    if "step" in temp_850.dims:
        temp_850 = temp_850.isel(step=step)
    if "step" in u_850.dims:
        u_850 = u_850.isel(step=step)
    if "step" in v_850.dims:
        v_850 = v_850.isel(step=step)
    if "step" in w_700.dims:
        w_700 = w_700.isel(step=step)

    if temp_850 is None or u_850 is None or v_850 is None or w_700 is None:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
        ax.set_axis_off()
        return

    temp = temp_850 - 273.15 if np.nanmax(temp_850) > 100 else temp_850
    w700 = w_700 * 3600   # 700hPa vertical velocity [hPa/h]

    lon2d, lat2d = get_lon_lat(temp_850)  # temp_850から緯度経度を抽出
    skip = 5

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 700hPa鉛直流
    cf = ax.contourf(
        lon2d, lat2d, w700,
        levels=np.linspace(-20, 20, 21),
        cmap="bwr", extend="both",
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa Vertical Velocity [hPa/h]", fontsize=8)

    # 850hPa等温線
    cs = ax.contour(
        lon2d, lat2d, temp,
        levels=np.arange(-20, 32, 2),
        colors="k", linewidths=0.5,
        transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)

    # 850hPa風ベクトル
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u_850[::skip, ::skip], v_850[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.8
    )

    ax.set_title("850hPa Temperature & Wind / 700hPa Vertical Velocity", fontsize=10, pad=10)
