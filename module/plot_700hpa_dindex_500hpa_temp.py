# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa Dewpoint Depression + 500hPa Temperature Contour Plot Module
# Compatible with GSM/MSM (by wrapper function)
# -----------------------------------------------
# 機能概要:
#   - 700hPa湿数（Dewpoint Depression）のカラーマップ塗り分け
#   - 500hPa等温線を重ねて描画
#   - GSM/MSMいずれもラッパーで呼び出せる汎用デザイン
#   - 拡張やパネル連結時も安全
# 利用例:
#   from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_700hpa_dindex_500hpa_temp_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# xarray Datasetから緯度経度グリッド2次元化
# -------------------------------------------------
def get_lon_lat(ds):
    """
    xarray.Datasetから2Dのlongitude/latitude配列を返す
    """
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# メイン描画関数（GSM/MSM共通）
# -------------------------------------------------
def plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM"):
    """
    Draw 700hPa dewpoint depression (color) and 500hPa temperature contour.
    （日本語：700hPa湿数の塗り分け＋500hPa等温線の重ね描き）
    - ax: PlateCarree投影のmatplotlib axes
    - ds: xarray.Dataset
    - model: "GSM" or "MSM"
    """
    lon2d, lat2d = get_lon_lat(ds)
    # --- 必要な変数を抽出 ---
    temp_500 = get_var(ds, "TMP_500mb")
    temp_700 = get_var(ds, "TMP_700mb")
    rh_700   = get_var(ds, "RH_700mb")
    if temp_500 is None or temp_700 is None or rh_700 is None:
        raise ValueError("Required 700/500hPa variables missing.")

    # --- ケルビン→摂氏変換 ---
    temp_500_c = temp_500 - 273.15
    temp_700_c = temp_700 - 273.15

    # --- 700hPa湿数（Dewpoint Depression, D = T - Td）を計算 ---
    dewpoint_700 = temp_700_c - (100 - rh_700) / 5  # 気象庁式の近似
    dindex_700 = temp_700_c - dewpoint_700  # ＝(100 - RH)/5

    # --- 湿数のカラーマップ設定（黄緑→黄）---
    colors = [
        (0.0, "#006400"),
        (0.25, "#32cd32"),
        (0.5, "#adff2f"),
        (0.75, "#ffff66"),
        (1.0, "#ffd700"),
    ]
    cmap = LinearSegmentedColormap.from_list("drywet", colors)

    # --- 地図範囲・海岸線 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 700hPa湿数 塗り分け ---
    cf = ax.contourf(
        lon2d, lat2d, dindex_700,
        levels=np.linspace(0, 30, 13),
        cmap=cmap, extend="max", alpha=0.8,
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa Dewpoint Depression [°C]", fontsize=8)

    # --- 500hPa等温線 ---
    cs = ax.contour(
        lon2d, lat2d, temp_500_c,
        levels=np.arange(-60, 0, 2),
        colors='navy', linewidths=0.7,
        linestyles='solid', transform=ccrs.PlateCarree(),
        zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)
    ax.set_title("700hPa Dewpoint Depression & 500hPa Temperature", fontsize=10, pad=10)

# -------------------------------------------------
# GSM/MSMラッパー関数
# -------------------------------------------------
def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds):
    """Wrapper for GSM data"""
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="GSM")

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds):
    """Wrapper for MSM data"""
    return plot_700hpa_dindex_500hpa_temp(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
