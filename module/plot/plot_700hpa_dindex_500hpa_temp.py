# ===============================================
# module/plot/plot_700hpa_dindex_500hpa_temp.py
# 700hPa湿数D-index＋500hPa気温等値線プロット
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var_2d, get_lon_lat
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
        raise ValueError("緯度経度配列の次元不正")
    return lon2d, lat2d

# module/plot/plot_700hpa_dindex_500hpa_temp.py
def plot_700hpa_dindex_500hpa_temp(ax, ds_dict, step=0):
    """
    700hPa湿数・500hPa気温（dict＋step方式）
    ds_dict: {"t_700":..., "r_700":..., "t_500":...}
    """
    for k in ["t_700", "r_700", "t_500"]:
        if ds_dict.get(k) is None:
            ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
            ax.coastlines(resolution="50m")
            ax.add_feature(cfeature.BORDERS, linestyle=":")
            ax.text(0.5, 0.5, f"NO DATA\n({k})", fontsize=14, color="gray",
                    ha="center", va="center", transform=ax.transAxes)
            return

    temp_700 = ds_dict["t_700"].isel(step=step)
    rh_700   = ds_dict["r_700"].isel(step=step)
    temp_500 = ds_dict["t_500"].isel(step=step)

    temp_700_c = temp_700 - 273.15
    temp_500_c = temp_500 - 273.15
    lon2d = temp_700["longitude"].values
    lat2d = temp_700["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    dindex_700 = (100.0 - rh_700) / 5.0

    colors = [
        (0.00, "#296A32"),
        (0.20, "#5CD25C"),
        (0.45, "#FFFF66"),
        (0.70, "#FFA500"),
        (1.00, "#FF0000"),
    ]
    cmap = LinearSegmentedColormap.from_list("dindex", colors)
    levels = np.arange(0, 30.1, 2)

    cf = ax.contourf(
        lon2d, lat2d, dindex_700,
        levels=levels, cmap=cmap, extend="max", alpha=0.9,
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.7, pad=0.03)
    cbar.set_label("700hPa D-index [°C]", fontsize=8)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.6, alpha=0.7)

    cs = ax.contour(
        lon2d, lat2d, temp_500_c,
        levels=np.arange(-60, 0, 2), colors='navy', linewidths=0.7,
        linestyles='solid', transform=ccrs.PlateCarree(), zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)

    ax.set_title("700hPa湿数D-index / 500hPa気温", fontsize=11, pad=10)
