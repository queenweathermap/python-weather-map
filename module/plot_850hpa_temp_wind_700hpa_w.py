# ===============================================
# module/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa Temperature & Wind + 700hPa Vertical Velocity Plot Module
# GSM/MSM両対応
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
from module.utils.var_utils import get_var_2d

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    lon = get_var_2d(ds, "longitude")
    lat = get_var_2d(ds, "latitude")
    # meshgrid必要な場合（1D→2D）
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    else:
        lon2d, lat2d = lon, lat
    return lon2d, lat2d

def plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=None, skip=5):
    """
    Draws 850hPa temperature contours, wind barbs, and 700hPa vertical velocity as color fill.
    - ax: PlateCarree投影matplotlib axes
    - ds: xarray.Dataset
    - model: "GSM"または"MSM"
    """
    # --- 必要な物理量を2Dで抽出 ---
    temp_850 = get_var_2d(ds, "TMP_850mb", level=850)
    u_850    = get_var_2d(ds, "UGRD_850mb", level=850)
    v_850    = get_var_2d(ds, "VGRD_850mb", level=850)
    w_700    = get_var_2d(ds, "VVEL_700mb", level=700)

    if temp_850 is None or u_850 is None or v_850 is None or w_700 is None:
        raise ValueError("Required 850/700hPa variables missing.")

    # Kelvin→Celsius
    temp = temp_850 - 273.15 if np.nanmax(temp_850) > 100 else temp_850
    w700 = w_700 * 3600   # 700hPa vertical velocity [hPa/h]

    lon2d, lat2d = get_lon_lat(ds)

    # --- 地図範囲・国境・海岸線 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 700hPa鉛直流（塗り分け、赤-青）---
    cf = ax.contourf(
        lon2d, lat2d, w700,
        levels=np.linspace(-20, 20, 21),
        cmap="bwr", extend="both",
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa Vertical Velocity [hPa/h]", fontsize=8)

    # --- 850hPa等温線（細線のみ、黒）---
    cs = ax.contour(
        lon2d, lat2d, temp,
        levels=np.arange(-20, 32, 2),
        colors="k", linewidths=0.5,
        transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)

    # --- 850hPa風ベクトル ---
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u_850[::skip, ::skip], v_850[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.8
    )

    ax.set_title("850hPa Temperature & Wind / 700hPa Vertical Velocity", fontsize=10, pad=10, fontproperties=prop)

# --- GSM/MSMラッパー関数 ---
def plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_850hpa_temp_wind_700hpa_w_msm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
