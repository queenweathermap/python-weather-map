# ===============================================
# module/plot/plot_300hpa_height_wind.py
# 300hPa Geopotential Height, Wind Speed, and Wind Vector Panel
# 2025-06-30 ChatGPT改訂：NO DATA時は変数名print＋日本地図のみ描画
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var
# 必要なら set_japanese_font() も有効化

def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_300hpa_height_wind(ax, ds):
    """300hPa等高度・風（NO DATA時は変数名print＋地図のみ描画）"""
    # --- データ取得 ---
    lon2d, lat2d = get_lon_lat(ds)
    hgt  = get_var(ds, "HGT_300mb")
    u    = get_var(ds, "UGRD_300mb")
    v    = get_var(ds, "VGRD_300mb")
    temp = get_var(ds, "TMP_300mb")  # 任意

    # --- 欠損チェック ---
    missing = []
    if hgt is None: missing.append("HGT_300mb")
    if u   is None: missing.append("UGRD_300mb")
    if v   is None: missing.append("VGRD_300mb")
    if missing:
        print(f"[NO DATA] 300hPa: {', '.join(missing)} がありません")
        # 日本地図のみ描画
        ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
        ax.coastlines(resolution="50m")
        ax.add_feature(cfeature.BORDERS, linestyle=":")
        ax.text(0.5, 0.5, f"NO DATA\n({', '.join(missing)})", fontsize=14, color="gray",
                ha="center", va="center", transform=ax.transAxes)
        # 軸を残すなら set_axis_off は不要
        return

    # --- 以降、通常描画 ---
    wspd = np.sqrt(u**2 + v**2) * 1.94384  # m/s→kt

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 等温線（任意: 必要ない場合は外す）
    if temp is not None:
        temp_c = temp - 273.15 if np.nanmax(temp) > 100 else temp
        t_levels = np.arange(-60, 6, 6)
        cs_temp = ax.contour(lon2d, lat2d, temp_c, levels=t_levels,
                             colors='blue', linewidths=0.8, linestyles='dashed',
                             transform=ccrs.PlateCarree())
        ax.clabel(cs_temp, fmt="%.0f", fontsize=7, colors="blue")

    # 等高度線（細線・太線両方）
    hgt_levels = np.arange(9600, 16001, 120)
    cs = ax.contour(lon2d, lat2d, hgt, levels=hgt_levels, colors="navy",
                    linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    bold_lv = np.arange(9600, 16001, 240)
    ax.contour(lon2d, lat2d, hgt, levels=bold_lv, colors="navy",
               linewidths=2.0, transform=ccrs.PlateCarree())

    # 風速コンター
    ws_levels = np.arange(20, 180, 20)
    ws = ax.contour(lon2d, lat2d, wspd, levels=ws_levels,
                    colors="gray", linestyles="solid", linewidths=0.5,
                    transform=ccrs.PlateCarree())
    ax.clabel(ws, fmt="%d", fontsize=7, colors="black")
    for level in ws_levels:
        wspd_east = np.where(u < 0, wspd, np.nan)
        cs_east = ax.contour(lon2d, lat2d, wspd_east, levels=[level],
                             colors="gray", linestyles="dashed", linewidths=0.7,
                             transform=ccrs.PlateCarree())
        ax.clabel(cs_east, fmt="%d", fontsize=7, colors="black")

    # 矢羽（間引き）
    skip = 5
    ax.quiver(lon2d[::skip, ::skip], lat2d[::skip, ::skip],
              u[::skip, ::skip], v[::skip, ::skip],
              transform=ccrs.PlateCarree(), scale=350, alpha=0.3)

    # 極大・極小表示（H/L）
    hgt_flat = hgt.flatten()
    hmax_indices = np.argpartition(hgt_flat, -2)[-2:]
    hmin_indices = np.argpartition(hgt_flat, 2)[:2]
    hmax_coords = np.unravel_index(hmax_indices, hgt.shape)
    hmin_coords = np.unravel_index(hmin_indices, hgt.shape)
    for j, i in zip(*hmax_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
    for j, i in zip(*hmin_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    ax.set_title("300hPa高度・風")

