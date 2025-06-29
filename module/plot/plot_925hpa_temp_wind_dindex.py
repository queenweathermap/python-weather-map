# ===============================================
# module/plot/plot_925hpa_temp_wind_dindex.py
# 925hPa Temperature, Wind, and Dewpoint Depression
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
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_925hpa_temp_wind_dindex(ax, ds):
    """
    925hPa気温・風・湿数（GSM/MSM両対応）
    Parameters
    ----------
    ax : matplotlib.axes.Axes
    ds : xarray.Dataset（stepで既にスライス済み！）
    """
    lon2d, lat2d = get_lon_lat(ds)

    try:
        temp = ds["t"].sel(isobaricInhPa=925).squeeze()
        u = ds["u"].sel(isobaricInhPa=925).squeeze()
        v = ds["v"].sel(isobaricInhPa=925).squeeze()
        rh = ds["r"].sel(isobaricInhPa=925).squeeze()
    except Exception:
        temp = get_var(ds, "TMP_925mb")
        u = get_var(ds, "UGRD_925mb")
        v = get_var(ds, "VGRD_925mb")
        rh = get_var(ds, "RH_925mb")
        if temp is None or u is None or v is None or rh is None:
            ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
            ax.set_axis_off()
            return
            
    # ... 以降はそのままプロット処理

    temp_c = temp - 273.15  # K→℃
    dewpoint = temp_c - (100 - rh) / 5
    dindex = temp_c - dewpoint

    skip = 5
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cs_temp = ax.contour(
        lon2d, lat2d, temp_c, levels=np.arange(-20, 36, 2), colors="k",
        linewidths=0.7, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs_temp, fontsize=6)
    cf = ax.contourf(
        lon2d, lat2d, dindex, levels=np.linspace(0, 30, 13),
        cmap="Greens", alpha=0.6, transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("925hPa Dewpoint Depression [℃]", fontsize=8)
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )
    ax.set_title("925hPa Temperature / Wind / Dewpoint Depression", fontsize=10, pad=10)
