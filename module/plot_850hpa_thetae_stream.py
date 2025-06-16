# ===============================================
# module/plot_850hpa_thetae_stream.py
# 850hPa相当温位＋流線（GSM/MSM対応）
# -----------------------------------------------
# 利用例:
#   from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_850hpa_thetae_stream_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']


def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_850hpa_thetae_stream(ax, ds, model="GSM", prop=None):
    """
    850hPa簡易相当温位（1K刻み/15Kごと太線）＋流線（GSM/MSM両対応）
    """
    lon2d, lat2d = get_lon_lat(ds)
    temp = get_var(ds, "TMP_850mb")
    rh   = get_var(ds, "RH_850mb")
    u    = get_var(ds, "UGRD_850mb")
    v    = get_var(ds, "VGRD_850mb")
    if temp is None or (rh is None and (u is None or v is None)):
        raise ValueError("850hPaの必要変数が欠損")
    # 簡易相当温位計算
    if rh is not None:
        Td = temp - (100 - rh) / 5
        thetae_like = temp + 0.2854 * Td
    else:
        thetae_like = temp

    min_thetae = int(np.nanmin(thetae_like) // 1 * 1)
    max_thetae = int(np.nanmax(thetae_like) // 1 * 1) + 1
    levels = np.arange(min_thetae, max_thetae + 1, 1)
    bold_levels = np.arange(min_thetae, max_thetae + 15, 15)

    # --- 相当温位等値線 ---
    cs1 = ax.contour(
        lon2d, lat2d, thetae_like, levels=levels,
        colors="#888888", linewidths=0.5, linestyles="-", transform=ccrs.PlateCarree()
    )
    cs2 = ax.contour(
        lon2d, lat2d, thetae_like, levels=bold_levels,
        colors="k", linewidths=1.2, linestyles="-", transform=ccrs.PlateCarree()
    )
    ax.clabel(cs2, fontsize=7, fmt="%.0f")

    # --- 流線（850hPa風） ---
    if u is not None and v is not None:
        ax.streamplot(
            lon2d, lat2d, u, v,
            density=1.3, color="#003366", linewidth=0.4,
            transform=ccrs.PlateCarree(), arrowsize=0.5
        )

    # --- 地図・装飾 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.4)
    ax.set_title("850hPa簡易相当温位（1K刻み/15Kごと太線）＋流線", fontsize=10, pad=10, fontproperties=prop)

# ======= ラッパー関数 =======
def plot_850hpa_thetae_stream_gsm(ax, ds, prop=None):
    return plot_850hpa_thetae_stream(ax, ds, model="GSM", prop=prop)

def plot_850hpa_thetae_stream_msm(ax, ds, prop=None):
    return plot_850hpa_thetae_stream(ax, ds, model="MSM", prop=prop)

# ===============================================
# END OF FILE
# ===============================================
