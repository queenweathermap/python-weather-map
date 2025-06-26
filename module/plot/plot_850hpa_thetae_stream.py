# ===============================================
# module/plot/plot_850hpa_thetae_stream.py
# 850hPa Equivalent Potential Temperature & Streamline Plot Module
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
from module.utils.var_utils import get_var

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_850hpa_thetae_stream(ax, ds, step=0):
    """
    850hPa相当温位・流線
    ax: PlateCarree axes, ds: xarray.Dataset, step: int
    """
    # MSM優先、なければGSM
    try:
        temp = ds["t"].sel(isobaricInhPa=850).isel(step=step).squeeze()
        rh   = ds["r"].sel(isobaricInhPa=850).isel(step=step).squeeze()
        u    = ds["u"].sel(isobaricInhPa=850).isel(step=step).squeeze()
        v    = ds["v"].sel(isobaricInhPa=850).isel(step=step).squeeze()
    except Exception:
        temp = get_var(ds, "TMP_850mb", step=step)
        rh   = get_var(ds, "RH_850mb", step=step)
        u    = get_var(ds, "UGRD_850mb", step=step)
        v    = get_var(ds, "VGRD_850mb", step=step)
        if temp is None or rh is None or u is None or v is None:
            ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
            ax.set_axis_off()
            return

    # 簡易相当温位計算（RH→Td近似→thetae_like）
    Td = temp - (100 - rh) / 5
    thetae_like = temp + 0.2854 * Td

    lon2d, lat2d = get_lon_lat(ds)
    min_thetae = int(np.nanmin(thetae_like) // 1 * 1)
    max_thetae = int(np.nanmax(thetae_like) // 1 * 1) + 1
    levels = np.arange(min_thetae, max_thetae + 1, 1)
    bold_levels = np.arange(min_thetae, max_thetae + 15, 15)

    cs1 = ax.contour(
        lon2d, lat2d, thetae_like, levels=levels,
        colors="#888888", linewidths=0.5, linestyles="-", transform=ccrs.PlateCarree()
    )
    cs2 = ax.contour(
        lon2d, lat2d, thetae_like, levels=bold_levels,
        colors="k", linewidths=1.2, linestyles="-", transform=ccrs.PlateCarree()
    )
    ax.clabel(cs2, fontsize=7, fmt="%.0f")

    # 流線
    ax.streamplot(
        lon2d, lat2d, u, v,
        density=1.3, color="#003366", linewidth=0.4,
        transform=ccrs.PlateCarree(), arrowsize=0.5
    )

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.4)
    ax.set_title("850hPa Equivalent Potential Temperature & Streamlines", fontsize=10, pad=10)
