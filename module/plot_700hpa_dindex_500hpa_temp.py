# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa湿数＋500hPa等温線描画モジュール
# GSM/MSM両対応
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

def get_var(ds, var):
    import xarray as xr
    if isinstance(ds, xr.Dataset):
        return ds[var].values if var in ds.variables else None
    elif isinstance(ds, xr.DataArray):
        return ds.values
    else:
        return None

def plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM"):
    lon2d, lat2d = get_lon_lat(ds)
    temp_500 = get_var(ds, "TMP_500mb")
    temp_700 = get_var(ds, "TMP_700mb")
    rh_700   = get_var(ds, "RH_700mb")
    if temp_500 is None or temp_700 is None or rh_700 is None:
        raise ValueError("必要な700/500hPa変数がありません")
    temp_500 = temp_500 - 273.15
    temp_700 = temp_700 - 273.15
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

def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM")

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
