# ===============================================
# module/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa温度・風＋700hPa鉛直流描画モジュール
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr

def get_lon_lat(ds):
    if isinstance(ds, xr.DataArray):
        ds = ds.to_dataset()
    lon = ds["longitude"].values
    lat = ds["latitude"].values
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    else:
        lon2d, lat2d = lon, lat
    return lon2d, lat2d

def _get_var(ds, var):
    if isinstance(ds, xr.DataArray):
        return ds.values
    elif isinstance(ds, xr.Dataset):
        if var in ds.variables:
            return ds[var].values
        elif hasattr(ds, "name") and ds.name == var:
            return ds.values
        else:
            return None
    else:
        return None

def plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=None, skip=5):
    lon2d, lat2d = get_lon_lat(ds)
    temp = _get_var(ds, "TMP_850mb")
    u = _get_var(ds, "UGRD_850mb")
    v = _get_var(ds, "VGRD_850mb")
    w700 = _get_var(ds, "VVEL_700mb")
    if temp is None or u is None or v is None or w700 is None:
        raise ValueError("850hPa/700hPa変数が欠損")
    temp = temp - 273.15
    w700 = w700 * 3600

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cf = ax.contourf(
        lon2d, lat2d, w700, levels=np.linspace(-20, 20, 21),
        cmap="bwr", extend="both", transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa鉛直流 [hPa/h]", fontsize=8)

    cs = ax.contour(
        lon2d, lat2d, temp, levels=np.arange(-20, 32, 2),
        colors="k", linewidths=0.5, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.8
    )
    ax.set_title("850hPa温度・風＋700hPa鉛直流", fontsize=10, pad=10, fontproperties=prop)

def plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_850hpa_temp_wind_700hpa_w_msm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="MSM", prop=prop, skip=skip)

# END OF FILE
