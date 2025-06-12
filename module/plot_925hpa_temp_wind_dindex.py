# ===============================================
# module/plot_925hpa_temp_wind_dindex.py
# 925hPa温度・風・湿数描画モジュール（GSM/MSM両対応）
# ===============================================
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

def get_lon_lat(ds):
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def get_var(ds, var):
    import xarray as xr
    if isinstance(ds, xr.Dataset):
        return ds[var].values if var in ds.variables else None
    elif isinstance(ds, xr.DataArray):
        return ds.values
    else:
        return None

def plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=None, skip=5):
    lon2d, lat2d = get_lon_lat(ds)
    temp = get_var(ds, "TMP_925mb")
    u = get_var(ds, "UGRD_925mb")
    v = get_var(ds, "VGRD_925mb")
    rh = get_var(ds, "RH_925mb")
    if temp is None or u is None or v is None or rh is None:
        raise ValueError("必要な925hPa変数がありません")
    temp = temp - 273.15
    dewpoint = temp - (100 - rh) / 5
    dindex = temp - dewpoint

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    cs_temp = ax.contour(lon2d, lat2d, temp, levels=np.arange(-20, 36, 2), colors="k", linewidths=0.7, transform=ccrs.PlateCarree())
    ax.clabel(cs_temp, fontsize=6)
    cf = ax.contourf(lon2d, lat2d, dindex, levels=np.linspace(0, 30, 13), cmap="Greens", alpha=0.6, transform=ccrs.PlateCarree())
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("925hPa湿数 [℃]", fontsize=8)
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )
    ax.set_title("925hPa温度・風・湿数", fontsize=10, pad=10, fontproperties=prop)

def plot_925hpa_temp_wind_dindex_gsm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_925hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
