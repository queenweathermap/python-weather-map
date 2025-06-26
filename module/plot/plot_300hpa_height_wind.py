# ===============================================
# module/plot_300hpa_height_wind.py
# 300hPa Geopotential Height, Wind Speed, and Wind Vector Panel (GSM/MSM supported)
# -----------------------------------------------
# 機能概要:
#   - 300hPa等高度線・等風速線・風ベクトルを同時に描画
#   - 気温等値線やH/L/W/Cマークも付与可能
#   - GSM・MSMどちらのデータも利用可（model引数で分岐）
# 利用例:
#   from module.plot_300hpa_height_wind import plot_300hpa_height_wind_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_300hpa_height_wind_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# 緯度経度グリッドをxarray.Datasetから抽出する関数
# -------------------------------------------------
def get_lon_lat(ds):
    """
    xarray.Datasetから2次元lon/lat配列を生成
    """
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# 300hPaパネル描画のメイン関数
# -------------------------------------------------
def plot_300hpa_height_wind(ax, ds, model="GSM", skip=5):
    lon2d, lat2d = get_lon_lat(ds)
    hgt = get_var(ds, "HGT_300mb")
    u    = get_var(ds, "UGRD_300mb")
    v    = get_var(ds, "VGRD_300mb")
    temp = get_var(ds, "TMP_300mb")

    # 1. 必要変数がなければreturn（落とさない）
    if hgt is None or u is None or v is None:
        print("[WARN] 300hPa 必須変数(hgt, u, v)が不足 → 描画スキップ")
        return

    # 以下はそのままでOK
    wspd = np.sqrt(u**2 + v**2) * 1.94384

    # 地図の範囲・海岸線
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 気温等値線（tempがあれば描く。なければ飛ばす）
    if temp is not None:
        temp_c = temp - 273.15 if np.nanmax(temp) > 100 else temp
        t_levels = np.arange(-60, 6, 6)
        cs_temp = ax.contour(lon2d, lat2d, temp_c, levels=t_levels,
                             colors='blue', linewidths=0.8, linestyles='dashed',
                             transform=ccrs.PlateCarree())
        ax.clabel(cs_temp, fmt="%.0f", fontsize=7, colors="blue")

    # --- 等高度線（通常/太線） ---
    hgt_levels = np.arange(9600, 16001, 120)
    cs = ax.contour(lon2d, lat2d, hgt, levels=hgt_levels, colors="navy",
                    linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    bold_lv = np.arange(9600, 16001, 240)
    bold = ax.contour(lon2d, lat2d, hgt, levels=bold_lv, colors="navy",
                      linewidths=2.0, transform=ccrs.PlateCarree())

    # --- 等風速線（西風＝実線, 東風＝破線） ---
    ws_levels = np.arange(20, 180, 20)
    ws = ax.contour(lon2d, lat2d, wspd, levels=ws_levels,
                    colors="gray", linestyles="solid", linewidths=0.5,
                    transform=ccrs.PlateCarree())
    ax.clabel(ws, fmt="%d", fontsize=7, colors="black")
    # East wind only: dashed lines
    for level in ws_levels:
        wspd_east = np.where(u < 0, wspd, np.nan)
        cs_east = ax.contour(lon2d, lat2d, wspd_east, levels=[level],
                             colors="gray", linestyles="dashed", linewidths=0.7,
                             transform=ccrs.PlateCarree())
        ax.clabel(cs_east, fmt="%d", fontsize=7, colors="black")

    # --- 風ベクトル ---
    ax.quiver(lon2d[::skip, ::skip], lat2d[::skip, ::skip],
              u[::skip, ::skip], v[::skip, ::skip],
              transform=ccrs.PlateCarree(), scale=350, alpha=0.3)

    # --- H/Lマーク（高度最大・最小） ---
    hgt_max = maximum_filter(hgt, size=9)
    hgt_min = minimum_filter(hgt, size=9)
    hgt_flat = hgt.flatten()
    hmax_indices = np.argpartition(hgt_flat, -2)[-2:]
    hmin_indices = np.argpartition(hgt_flat, 2)[:2]
    hmax_coords = np.unravel_index(hmax_indices, hgt.shape)
    hmin_coords = np.unravel_index(hmin_indices, hgt.shape)
    for j, i in zip(*hmax_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
    for j, i in zip(*hmin_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    # --- W/Cマーク（最暖域/最寒域：気温最大・最小） ---
    if temp is not None:
        temp_flat = temp.flatten()
        w_indices = np.argpartition(temp_flat, -3)[-3:]
        c_indices = np.argpartition(temp_flat, 3)[:3]
        w_coords = np.unravel_index(w_indices, temp.shape)
        c_coords = np.unravel_index(c_indices, temp.shape)
        for j, i in zip(*w_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'W', color='red', fontsize=13, weight='bold', ha='center', va='center')
        for j, i in zip(*c_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'C', color='blue', fontsize=13, weight='bold', ha='center', va='center')

    ax.set_title("300hPa Height & Wind", fontsize=10, pad=10)

# -------------------------------------------------
# ラッパー関数（GSM/MSM両対応でimportしやすく）
# -------------------------------------------------
def plot_300hpa_height_wind_gsm(ax, ds):
    """GSM向け300hPa描画ラッパー"""
    return plot_300hpa_height_wind(ax, ds, model="GSM")

def plot_300hpa_height_wind_msm(ax, ds):
    """MSM向け300hPa描画ラッパー"""
    return plot_300hpa_height_wind(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
