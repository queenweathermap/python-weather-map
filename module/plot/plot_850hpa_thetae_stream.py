# ===============================================
# module/plot_850hpa_thetae_stream.py
# 850hPa Equivalent Potential Temperature & Streamline Plot Module（GSM/MSM対応）
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

def plot_850hpa_thetae_stream(ax, ds, step=0):
    """850hPa相当温位・流線"""
    lon2d, lat2d = get_lon_lat(ds)

    if model == "MSM":
        # MSM用（isobaricInhPa=850を抜く。湿度は"r"で相対湿度）
        try:
            temp = ds["t"].sel(isobaricInhPa=850).squeeze()        # [K]
            rh   = ds["r"].sel(isobaricInhPa=850).squeeze()        # [%]
            u    = ds["u"].sel(isobaricInhPa=850).squeeze()
            v    = ds["v"].sel(isobaricInhPa=850).squeeze()
        except Exception as e:
            print(f"Error extracting MSM 850hPa variables: {e}")
            raise ValueError("Required 850hPa variables missing (MSM).")
    else:
        # GSM用
        from module.utils.var_utils import get_var
        temp = get_var(ds, "TMP_850mb")
        rh   = get_var(ds, "RH_850mb")
        u    = get_var(ds, "UGRD_850mb")
        v    = get_var(ds, "VGRD_850mb")
        if temp is None or (rh is None and (u is None or v is None)):
            raise ValueError("Required 850hPa variables missing (GSM).")

    # ---- 簡易相当温位計算（公式版は別途。ここではRHから近似計算）----
    if rh is not None:
        Td = temp - (100 - rh) / 5
        thetae_like = temp + 0.2854 * Td
    else:
        thetae_like = temp

    min_thetae = int(np.nanmin(thetae_like) // 1 * 1)
    max_thetae = int(np.nanmax(thetae_like) // 1 * 1) + 1
    levels = np.arange(min_thetae, max_thetae + 1, 1)
    bold_levels = np.arange(min_thetae, max_thetae + 15, 15)

    # --- 等相当温位線（細線: 1K刻み, 太線: 15K刻み）---
    cs1 = ax.contour(
        lon2d, lat2d, thetae_like, levels=levels,
        colors="#888888", linewidths=0.5, linestyles="-", transform=ccrs.PlateCarree()
    )
    cs2 = ax.contour(
        lon2d, lat2d, thetae_like, levels=bold_levels,
        colors="k", linewidths=1.2, linestyles="-", transform=ccrs.PlateCarree()
    )
    ax.clabel(cs2, fontsize=7, fmt="%.0f")

    # --- 流線 ---
    if u is not None and v is not None:
        ax.streamplot(
            lon2d, lat2d, u, v,
            density=1.3, color="#003366", linewidth=0.4,
            transform=ccrs.PlateCarree(), arrowsize=0.5
        )

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.4)
    ax.set_title("850hPa Equivalent Potential Temperature & Streamlines", fontsize=10, pad=10, fontproperties=prop)

def plot_850hpa_thetae_stream_gsm(ax, ds, prop=None):
    return plot_850hpa_thetae_stream(ax, ds, model="GSM", prop=prop)

def plot_850hpa_thetae_stream_msm(ax, ds, prop=None):
    return plot_850hpa_thetae_stream(ax, ds, model="MSM", prop=prop)

# ===============================================
# END OF FILE
# ===============================================
