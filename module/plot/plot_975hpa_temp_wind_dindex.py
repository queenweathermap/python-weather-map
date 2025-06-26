# ===============================================
# module/plot_975hpa_temp_wind_dindex.py
# 975hPa Temperature, Wind, and Dewpoint Depression Plot Module（全国MSM用・GSMも拡張可能）
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

def plot_975hpa_temp_wind_dindex(ax, ds, step=0):
    """975hPa気温・風・湿数"""
    """
    Draws 975hPa temperature (contour), wind (vector), and dewpoint depression (color filled).
    - ax: PlateCarree axes
    - ds: xarray.Dataset
    - model: "MSM" or "GSM" (将来的拡張)
    - prop: フォント設定
    - skip: 風ベクトル間引き
    """
    lon2d, lat2d = get_lon_lat(ds)
    if model == "MSM":
        try:
            temp = ds["t"].sel(isobaricInhPa=975).squeeze()    # K
            u = ds["u"].sel(isobaricInhPa=975).squeeze()
            v = ds["v"].sel(isobaricInhPa=975).squeeze()
            rh = ds["r"].sel(isobaricInhPa=975).squeeze()
        except Exception as e:
            print(f"Error extracting MSM 975hPa variables: {e}")
            raise ValueError("Required 975hPa variables missing (MSM).")
    else:
        # GSM仮実装（必要ならget_varで取得）
        from module.utils.var_utils import get_var
        temp = get_var(ds, "TMP_975mb")
        u = get_var(ds, "UGRD_975mb")
        v = get_var(ds, "VGRD_975mb")
        rh = get_var(ds, "RH_975mb")
        if temp is None or u is None or v is None or rh is None:
            raise ValueError("Required 975hPa variables missing (GSM).")

    temp_c = temp - 273.15
    dewpoint = temp_c - (100 - rh) / 5.0
    dindex = temp_c - dewpoint

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
    cbar.set_label("975hPa Dewpoint Depression [℃]", fontsize=8)

    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )

    ax.set_title("975hPa Temperature / Wind / Dewpoint Depression", fontsize=10, pad=10, fontproperties=prop)

def plot_975hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    return plot_975hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

def plot_975hpa_temp_wind_dindex_gsm(ax, ds, prop=None, skip=5):
    return plot_975hpa_temp_wind_dindex(ax, ds, model="GSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
