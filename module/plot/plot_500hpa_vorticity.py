# ===============================================
# module/plot/plot_500hpa_vorticity.py
# 500hPa Geopotential Height + Positive Vorticity Area
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

# module/plot/plot_500hpa_vorticity.py
def plot_500hpa_vorticity(ds, ax, step=None, **kwargs):
    """500hPa等高度・正渦度（オレンジ）"""
    import metpy.calc as mpcalc
    from metpy.units import units

    hgt   = get_var(ds, "HGT_500mb")
    ugrd  = get_var(ds, "UGRD_500mb")
    vgrd  = get_var(ds, "VGRD_500mb")

    if hgt is None or ugrd is None or vgrd is None:
        ax.text(0.5, 0.5, "NO DATA", fontsize=12, color="gray", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return


    ugrd = ugrd * units('m/s')
    vgrd = vgrd * units('m/s')
    lon2d, lat2d = get_lon_lat(ds)

    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cs = ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60),
                    colors="navy", linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120),
               colors="navy", linewidths=2.0, transform=ccrs.PlateCarree())

    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(lon2d, lat2d, vorticity_masked, levels=[0, 1e-5],
                colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree())

    ax.set_title("500hPa Vorticity", fontsize=10, pad=10)
