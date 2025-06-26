# ===============================================
# module/plot_925hpa_temp_wind_dindex.py
# 925hPa Temperature, Wind, and Dewpoint Depression Plot Module（GSM/MSM両対応）
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=None, skip=5):
    """
    Draws 925hPa temperature (contour), wind (vector), and dewpoint depression (color filled).
    - ax: PlateCarree axes
    - ds: xarray.Dataset
    - model: "GSM" or "MSM"
    - prop: フォント設定
    - skip: 風ベクトル間引き
    """
    lon2d, lat2d = get_lon_lat(ds)

    if model == "MSM":
        # MSM: 変数名(t/u/v/r)、層選択
        try:
            temp = ds["t"].sel(isobaricInhPa=925).squeeze()    # [K]
            u = ds["u"].sel(isobaricInhPa=925).squeeze()
            v = ds["v"].sel(isobaricInhPa=925).squeeze()
            rh = ds["r"].sel(isobaricInhPa=925).squeeze()
        except Exception as e:
            print(f"Error extracting MSM 925hPa variables: {e}")
            raise ValueError("Required 925hPa variables missing (MSM).")
    else:
        # GSM: 通常通り
        from module.utils.var_utils import get_var
        temp = get_var(ds, "TMP_925mb")
        u = get_var(ds, "UGRD_925mb")
        v = get_var(ds, "VGRD_925mb")
        rh = get_var(ds, "RH_925mb")
        if temp is None or u is None or v is None or rh is None:
            raise ValueError("Required 925hPa variables missing (GSM).")

    temp = temp - 273.15  # K→℃
    dewpoint = temp - (100 - rh) / 5
    dindex = temp - dewpoint

    # --- 地図基本設定 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 925hPa気温 等値線 ---
    cs_temp = ax.contour(
        lon2d, lat2d, temp, levels=np.arange(-20, 36, 2), colors="k",
        linewidths=0.7, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs_temp, fontsize=6)
    # --- 925hPa湿数 塗り分け ---
    cf = ax.contourf(
        lon2d, lat2d, dindex, levels=np.linspace(0, 30, 13),
        cmap="Greens", alpha=0.6, transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("925hPa Dewpoint Depression [℃]", fontsize=8)
    # --- 925hPa風ベクトル ---
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )
    ax.set_title("925hPa Temperature / Wind / Dewpoint Depression", fontsize=10, pad=10, fontproperties=prop)

# -------------------------------------------------
# GSM/MSMラッパー関数
# -------------------------------------------------
def plot_925hpa_temp_wind_dindex_gsm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_925hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
