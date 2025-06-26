# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa湿数D-index＋500hPa気温等値線プロット
# GSM/MSM両対応ラッパー付き・完全独立版
# ===============================================

import numpy as np
import matplotlib
matplotlib.use("Agg")  # バックエンド明示（CLI環境対策）
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap

from module.utils.var_utils import get_var_2d, get_var

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    """
    xarray.Datasetから経度・緯度の2次元配列を返す
    """
    lon = get_var(ds, "longitude")
    lat = get_var(ds, "latitude")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の次元不正")
    return lon2d, lat2d

def plot_700hpa_dindex_500hpa_temp(ax, ds, step=0):
    """700hPa湿数・500hPa気温"""
    """
    700hPa湿数D-index（露点差/色塗り）と500hPa気温等値線（navy）を描画
    ・ax: PlateCarree投影Matplotlib Axes
    ・ds: xarray.Dataset（多次元対応）
    ・time_idx: どの時刻を描くか（0=初期）
    """
    try:
        # データ取得
        temp_700 = get_var_2d(ds, "TMP_700mb", level=700, time_idx=time_idx)
        rh_700   = get_var_2d(ds, "RH_700mb",  level=700, time_idx=time_idx)
        temp_500 = get_var_2d(ds, "TMP_500mb", level=500, time_idx=time_idx)
    except Exception as e:
        ax.text(0.5, 0.5, f"NO DATA ({str(e)})", fontsize=12, color="gray", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    if temp_700 is None or temp_500 is None or rh_700 is None:
        ax.text(0.5, 0.5, "NO DATA", fontsize=14, color="gray", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    # Kelvin→Celsius
    temp_700_c = temp_700 - 273.15
    temp_500_c = temp_500 - 273.15

    # 緯度経度
    lon2d, lat2d = get_lon_lat(ds)

    # 700hPa D-index = (100 - RH)/5
    dindex_700 = (100.0 - rh_700) / 5.0

    # カラーマップ（緑→黄→橙→赤）
    colors = [
        (0.00, "#296A32"),
        (0.20, "#5CD25C"),
        (0.45, "#FFFF66"),
        (0.70, "#FFA500"),
        (1.00, "#FF0000"),
    ]
    cmap = LinearSegmentedColormap.from_list("dindex", colors)
    levels = np.arange(0, 30.1, 2)

    # 色塗り
    cf = ax.contourf(
        lon2d, lat2d, dindex_700,
        levels=levels, cmap=cmap, extend="max", alpha=0.9,
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.7, pad=0.03)
    cbar.set_label("700hPa D-index [°C]", fontsize=8)

    # 地図範囲・海岸線
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.6, alpha=0.7)

    # 500hPa等温線
    cs = ax.contour(
        lon2d, lat2d, temp_500_c,
        levels=np.arange(-60, 0, 2), colors='navy', linewidths=0.7,
        linestyles='solid', transform=ccrs.PlateCarree(), zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)

    ax.set_title("700hPa湿数D-index / 500hPa気温", fontsize=11, pad=10)

def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds, time_idx=0):
    """GSM用ラッパー"""
    return plot_700hpa_dindex_500hpa_temp(ax, ds, time_idx=time_idx)

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds, time_idx=0):
    """MSM用ラッパー"""
    return plot_700hpa_dindex_500hpa_temp(ax, ds, time_idx=time_idx)

# ===============================================
# END OF FILE
# ===============================================
