# ===============================================
# module/plot_500hpa_vorticity.py
# 500hPa等高度線＋渦度（正の渦度領域に半透明オレンジ）描画モジュール
# ===============================================
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter

def get_lon_lat(ds):
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def get_var(ds, var):
    import xarray as xr
    if isinstance(ds, xr.DataArray):
        return np.asarray(ds)
    if var in ds.variables:
        return np.asarray(ds[var])
    return None

def plot_500hpa_vorticity(ax, ds, model="GSM", prop=None):
    import metpy.calc as mpcalc
    from metpy.units import units

    hgt   = get_var(ds, "HGT_500mb")
    ugrd  = get_var(ds, "UGRD_500mb") * units('m/s')
    vgrd  = get_var(ds, "VGRD_500mb") * units('m/s')
    lon2d, lat2d = get_lon_lat(ds)

    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cs = ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60), colors="navy", linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120), colors="navy", linewidths=2.0, transform=ccrs.PlateCarree())

    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(lon2d, lat2d, vorticity_masked, levels=[0, 1e-5], colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree())

    ax.set_title("500hPa等高度線・渦度", fontsize=10, pad=10, fontproperties=prop)

def plot_500hpa_vorticity_gsm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="GSM", prop=prop)

def plot_500hpa_vorticity_msm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="MSM", prop=prop)
# ===============================================
# END OF FILE
# ===============================================
