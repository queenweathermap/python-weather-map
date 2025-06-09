# ===============================================
# plot_surface_pressure_wind_precip.py
# 地上海面更正気圧・風・降水量 描画モジュール
# GSM/MSM両対応（引数 model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 利用例:
#   from module.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_surface_pressure_and_wind_gsm(ax, ds)
#   plt.show()
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

def plot_surface_pressure_and_wind(ax, ds, model="GSM", prop=None, skip=5):
    """
    地上海面更正気圧・風・降水量の描画（GSM/MSM両対応）
    """
    lon2d, lat2d = get_lon_lat(ds)

    # モデルごとの変数取得（GSM/MSM共通）
    prmsl = ds.get("PRMSL_meansealevel", None)
    u10 = ds.get("UGRD_10maboveground", None)
    v10 = ds.get("VGRD_10maboveground", None)
    precip = ds.get("APCP_surface", None)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 海面更正気圧：等圧線 ---
    if prmsl is not None:
        prmsl_hpa = prmsl.values / 100  # hPa
        levels_fine = np.arange(900, 1101, 1)
        cs = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_fine, colors='k', linewidths=0.6,
            transform=ccrs.PlateCarree()
        )
        levels_bold = np.arange(900, 1101, 4)
        cs_bold = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_bold, colors='k', linewidths=2.0,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(cs, fmt="%.0f", fontsize=6)
        label_texts = ax.clabel(cs_bold, fmt="%.0f", fontsize=8, colors='k')
        for txt in label_texts:
            txt.set_fontweight('bold')

        # H/Lマーク
        prmsl_max = maximum_filter(prmsl_hpa, size=5)
        prmsl_min = minimum_filter(prmsl_hpa, size=5)
        prmsl_flat = prmsl_hpa.flatten()
        hmax_indices = np.argpartition(prmsl_flat, -2)[-2:]
        hmin_indices = np.argpartition(prmsl_flat, 2)[:2]
        hmax_coords = np.unravel_index(hmax_indices, prmsl_hpa.shape)
        hmin_coords = np.unravel_index(hmin_indices, prmsl_hpa.shape)
        for j, i in zip(*hmax_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
        for j, i in zip(*hmin_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    # --- 10m風ベクトル ---
    if u10 is not None and v10 is not None:
        ax.quiver(
            lon2d[::skip, ::skip], lat2d[::skip, ::skip],
            u10.values[::skip, ::skip], v10.values[::skip, ::skip],
            transform=ccrs.PlateCarree(), scale=500, width=0.002, alpha=0.8
        )

    # --- 降水量 ---
    if precip is not None:
        cf = ax.contourf(
            lon2d, lat2d, precip.values,
            levels=np.arange(0, 51, 5), cmap="Blues", alpha=0.4,
            transform=ccrs.PlateCarree()
        )
        cb = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
        cb.set_label("降水量 [mm]", fontsize=8, fontproperties=prop)

    ax.set_title("海面更正気圧・地上風・降水量", fontsize=10, pad=10, fontproperties=prop)

# ======= ラッパー関数 =======
def plot_surface_pressure_and_wind_gsm(ax, ds, prop=None, skip=5):
    return plot_surface_pressure_and_wind(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_surface_pressure_and_wind_msm(ax, ds, prop=None, skip=5):
    return plot_surface_pressure_and_wind(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
