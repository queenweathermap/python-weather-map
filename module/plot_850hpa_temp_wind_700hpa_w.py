# ===============================================
# module/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa Temperature & Wind + 700hPa Vertical Velocity Plot Module
# GSM/MSM両対応（model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 機能概要:
#   - 850hPa等温線＋850hPa風ベクトルを描画
#   - 700hPa鉛直流（垂直風）の塗り分けも同時に表示
#   - GSM/MSMどちらも呼び出し関数一つで対応
#   - プロダクトの物理的意味や視覚的意義も維持
# 利用例:
#   from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# Datasetから緯度経度2D配列を生成
# -------------------------------------------------
def get_lon_lat(ds):
    """
    xarray.Datasetから2次元緯度経度配列を返す（日本語コメント付き）
    - 1次元しかない場合meshgrid化
    """
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# メイン描画関数（850hPa温度・風＋700hPa鉛直流、GSM/MSM共通）
# -------------------------------------------------
def plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=None, skip=5):
    """
    Draws 850hPa temperature contours, wind barbs, and 700hPa vertical velocity as color fill.
    （日本語：850hPaの等温線＋風＋700hPa鉛直流の塗り分け）
    - ax: PlateCarree投影matplotlib axes
    - ds: xarray.Dataset
    - model: "GSM"または"MSM"
    - prop: フォント設定（オプション）
    - skip: 風ベクトルの間引き間隔
    """
    lon2d, lat2d = get_lon_lat(ds)
    temp_850 = get_var(ds, "TMP_850mb")
    u_850    = get_var(ds, "UGRD_850mb")
    v_850    = get_var(ds, "VGRD_850mb")
    w_700    = get_var(ds, "VVEL_700mb")
    if temp_850 is None or u_850 is None or v_850 is None or w_700 is None:
        raise ValueError("Required 850/700hPa variables missing.")

    temp = temp_850 - 273.15  # 850hPa temperature [°C]
    w700 = w_700 * 3600       # 700hPa vertical velocity [hPa/h]（上昇正・下降負、気象庁標準）

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

# -------------------------------------------------
# GSM/MSMラッパー関数
# -------------------------------------------------
def plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds, prop=None, skip=5):
    """Wrapper for GSM data"""
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_850hpa_temp_wind_700hpa_w_msm(ax, ds, prop=None, skip=5):
    """Wrapper for MSM data"""
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
