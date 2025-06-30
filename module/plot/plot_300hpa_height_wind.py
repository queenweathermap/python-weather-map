# module/plot/plot_300hpa_height_wind.py
# ===============================================
# 300hPa Geopotential Height, Wind Speed, and Wind Vector Panel
# 2025-06-30 ChatGPT改訂：NO DATA時は変数名print＋日本地図のみ描画
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter

def get_plevel_var(ds, var_name, level_hpa):
    """dsから指定変数(var_name)の level_hpa [hPa] 層のみ2D抽出"""
    if var_name not in ds.variables:
        return None
    arr = ds[var_name]
    if "isobaricInhPa" not in arr.dims:
        return arr  # 層なし
    # 最も近い層のインデックス取得
    levels = ds["isobaricInhPa"].values
    idx = np.argmin(np.abs(levels - level_hpa))
    return arr.isel(isobaricInhPa=idx)

def get_lon_lat(ds):
    lon = ds["longitude"]
    lat = ds["latitude"]
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の形状が不正")
    return lon2d, lat2d

def plot_300hpa_height_wind(ax, ds):
    """
    300hPa等高度・風パネル
    ・NO DATA時は変数名print＋地図のみ描画
    """
    print("ds.variables:", list(ds.variables))
    print("isobaricInhPa:", ds["isobaricInhPa"].values)
    # 300hPa層の変数を抽出（cfgrib→短名＋層指定対応）
    hgt  = get_plevel_var(ds, "gh", 300)
    u    = get_plevel_var(ds, "u", 300)
    v    = get_plevel_var(ds, "v", 300)
    temp = get_plevel_var(ds, "t", 300)  # 任意

    # 欠損チェック
    missing = []
    if hgt is None: missing.append("gh@300")
    if u   is None: missing.append("u@300")
    if v   is None: missing.append("v@300")
    if missing:
        print(f"[NO DATA] 300hPa: {', '.join(missing)} がありません")
        ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
        ax.coastlines(resolution="50m")
        ax.add_feature(cfeature.BORDERS, linestyle=":")
        ax.text(0.5, 0.5, f"NO DATA\n({', '.join(missing)})", fontsize=14, color="gray",
                ha="center", va="center", transform=ax.transAxes)
        return

    # 緯度経度
    lon2d, lat2d = get_lon_lat(ds)

    # 風速
    wspd = np.sqrt(u**2 + v**2) * 1.94384  # m/s→kt

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 等温線（任意: 必要な場合のみ） ---
    if temp is not None:
        temp_c = temp - 273.15 if np.nanmax(temp) > 100 else temp
        t_levels = np.arange(-60, 6, 6)
        cs_temp = ax.contour(lon2d, lat2d, temp_c, levels=t_levels,
                             colors='blue', linewidths=0.8, linestyles='dashed',
                             transform=ccrs.PlateCarree())
        ax.clabel(cs_temp, fmt="%.0f", fontsize=7, colors="blue")

    # --- 等高度線（細・太両方） ---
    hgt_levels = np.arange(9600, 16001, 120)
    cs = ax.contour(lon2d, lat2d, hgt, levels=hgt_levels, colors="navy",
                    linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    bold_lv = np.arange(9600, 16001, 240)
    ax.contour(lon2d, lat2d, hgt, levels=bold_lv, colors="navy",
               linewidths=2.0, transform=ccrs.PlateCarree())

    # --- 風速コンター ---
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

    # --- 風矢羽 ---
    skip = 5
    ax.quiver(lon2d[::skip, ::skip], lat2d[::skip, ::skip],
              u[::skip, ::skip], v[::skip, ::skip],
              transform=ccrs.PlateCarree(), scale=350, alpha=0.3)

    # --- H/L（極大・極小） ---
    hgt_flat = hgt.values.flatten()
    hmax_indices = np.argpartition(hgt_flat, -2)[-2:]
    hmin_indices = np.argpartition(hgt_flat, 2)[:2]
    hmax_coords = np.unravel_index(hmax_indices, hgt.shape)
    hmin_coords = np.unravel_index(hmin_indices, hgt.shape)
    for j, i in zip(*hmax_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
    for j, i in zip(*hmin_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    ax.set_title("300hPa高度・風")
