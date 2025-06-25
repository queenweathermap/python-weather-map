# ===============================================
# module/plot_700hpa_dindex_500hpa_temp.py
# 700hPa Dewpoint Depression (D-index) + 500hPa Temperature Contour Plot
# Compatible with GSM/MSM (by wrapper function)
# ===============================================
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var_2d, get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

def get_lon_lat(ds):
    lon = get_var(ds, "longitude")
    lat = get_var(ds, "latitude")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度次元エラー")
    return lon2d, lat2d

def plot_700hpa_dindex_500hpa_temp(ax, ds, time_idx=0):
    """
    700hPa湿数（D-index/露点差, 色塗り）＋500hPa気温等値線（navy）を描画
    - ax: matplotlib axes
    - ds: xarray.Dataset（全時刻分OK）
    - time_idx: 何番目の時刻を描画するか
    """
    try:
        temp_700 = get_var_2d(ds, "TMP_700mb", level=700, time_idx=time_idx)
        rh_700   = get_var_2d(ds, "RH_700mb",  level=700, time_idx=time_idx)
        temp_500 = get_var_2d(ds, "TMP_500mb", level=500, time_idx=time_idx)
    except Exception as e:
        ax.text(0.5, 0.5, f"No Data ({str(e)})", ha="center", va="center", fontsize=10, color="gray")
        return

    if temp_700 is None or temp_500 is None:
        ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=12, color="gray")
        return

    # --- Kelvin→Celsius ---
    temp_700_c = temp_700 - 273.15
    temp_500_c = temp_500 - 273.15

    # --- 緯度経度2D ---
    lon2d, lat2d = get_lon_lat(ds)

    # --- 700hPa湿数D-index計算と描画 ---
    if rh_700 is not None:
        # 露点温度Td=気温-((100-相対湿度)/5) → D-index = 気温 - Td
        dewpoint_700 = temp_700_c - (100 - rh_700) / 5
        dindex_700 = temp_700_c - dewpoint_700  # = (100 - RH) / 5
        # カラーマップ設定
        colors = [
            (0.0, "#006400"),
            (0.25, "#32cd32"),
            (0.5, "#adff2f"),
            (0.75, "#ffff66"),
            (1.0, "#ffd700"),
        ]
        cmap = LinearSegmentedColormap.from_list("drywet", colors)
        cf = ax.contourf(
            lon2d, lat2d, dindex_700,
            levels=np.linspace(0, 30, 13),
            cmap=cmap, extend="max", alpha=0.8,
            transform=ccrs.PlateCarree()
        )
        cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
        cbar.set_label("700hPa Dewpoint Depression [°C]", fontsize=8)
    else:
        # --- 湿度が無い場合は気温背景 ---
        cf = ax.contourf(
            lon2d, lat2d, temp_700_c,
            levels=np.arange(-40, 20, 2),
            cmap="coolwarm", alpha=0.5, transform=ccrs.PlateCarree()
        )
        cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
        cbar.set_label("700hPa Temperature [°C]", fontsize=8)

    # --- 地図範囲・海岸線 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 500hPa等温線 ---
    cs = ax.contour(
        lon2d, lat2d, temp_500_c,
        levels=np.arange(-60, 0, 2),
        colors='navy', linewidths=0.7,
        linestyles='solid', transform=ccrs.PlateCarree(),
        zorder=10
    )
    ax.clabel(cs, fmt="%d", fontsize=6)
    ax.set_title("700hPa D-index/Temp & 500hPa Temp", fontsize=10, pad=10)

def plot_700hpa_dindex_500hpa_temp_gsm(ax, ds, time_idx=0):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, time_idx=time_idx)

def plot_700hpa_dindex_500hpa_temp_msm(ax, ds, time_idx=0):
    return plot_700hpa_dindex_500hpa_temp(ax, ds, time_idx=time_idx)

# ===============================================
# END OF FILE
# ===============================================
