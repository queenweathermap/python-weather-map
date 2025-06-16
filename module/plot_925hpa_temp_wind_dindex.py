# ===============================================
# module/plot_925hpa_temp_wind_dindex.py
# 925hPa Temperature, Wind, and Dewpoint Depression Plot Module（GSM/MSM両対応）
# -----------------------------------------------
# 日本語コメント多数：925hPaの気温・風・湿数（湿数=気温-露点温度）を地図上に可視化します
# 利用例:
#   from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_925hpa_temp_wind_dindex_gsm(ax, ds)
#   plt.show()
# -----------------------------------------------
# モデル引数"model"は将来的なフォーマット差異を考慮した汎用設計
# ===============================================

import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# Datasetから緯度経度2D配列を取得（meshgrid変換も自動対応）
# -------------------------------------------------
def get_lon_lat(ds):
    """
    Converts xarray Dataset lon/lat to 2D meshgrid arrays.
    日本語：1次元格子の場合も2次元化して返す
    """
    lon2d = get_var(ds, "longitude")
    lat2d = get_var(ds, "latitude")
    if lon2d is not None and lat2d is not None and lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# 925hPa温度・風・湿数を描画するメイン関数
# -------------------------------------------------
def plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=None, skip=5):
    """
    Draws 925hPa temperature (contour), wind (vector), and dewpoint depression (color filled).
    日本語：925hPaの気温・風（ベクトル）・湿数（色塗り）を同時に描画
    - ax: PlateCarree axes
    - ds: xarray.Dataset
    - model: "GSM"または"MSM"
    - prop: フォント設定
    - skip: 風ベクトルの間引き間隔
    """
    lon2d, lat2d = get_lon_lat(ds)
    temp = get_var(ds, "TMP_925mb")
    u = get_var(ds, "UGRD_925mb")
    v = get_var(ds, "VGRD_925mb")
    rh = get_var(ds, "RH_925mb")
    if temp is None or u is None or v is None or rh is None:
        raise ValueError("Required 925hPa variables are missing.")
    temp = temp - 273.15  # 絶対温度→摂氏
    dewpoint = temp - (100 - rh) / 5  # 露点温度（近似）
    dindex = temp - dewpoint  # 湿数

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
    """Wrapper for GSM data."""
    return plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_925hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    """Wrapper for MSM data."""
    return plot_925hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
