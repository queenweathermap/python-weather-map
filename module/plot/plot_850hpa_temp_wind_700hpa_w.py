# ===============================================================
# module/plot/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa温度・風＋700hPa鉛直流（dict＋step専用バージョン！）
# ===============================================================
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.utils.var_utils import get_var_2d, get_lon_lat
from scipy.ndimage import maximum_filter, minimum_filter
from module.utils.var_utils import get_var

from module.plot.plot_utils import set_japanese_font, plot_no_data_japan_map
set_japanese_font()  # 日本語フォントを全描画で有効化


def get_lon_lat(dataarr):
    lon = dataarr["longitude"].values
    lat = dataarr["latitude"].values
    if lon.ndim == 1 and lat.ndim == 1:
        lon, lat = np.meshgrid(lon, lat)
    return lon, lat

def plot_850hpa_temp_wind_700hpa_w(ax, ds_dict, step=0):
    """
    850hPa温度・風＋700hPa鉛直流
    ds_dict: {"t_850":..., "u_850":..., "v_850":..., "w_700":...}
    step: スライス番号
    """
    for k in ["t_850", "u_850", "v_850", "w_700"]:
        v = ds_dict.get(k)
        if v is None:
            ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
            ax.coastlines(resolution="50m")
            ax.add_feature(cfeature.BORDERS, linestyle=":")
            ax.text(0.5, 0.5, f"NO DATA\n({k})", fontsize=14, color="gray",
                    ha="center", va="center", transform=ax.transAxes)
            return

    # データ取り出し
    temp_850 = ds_dict["t_850"].isel(step=step)
    u_850    = ds_dict["u_850"].isel(step=step)
    v_850    = ds_dict["v_850"].isel(step=step)
    w_700    = ds_dict["w_700"].isel(step=step)

    # 温度K→℃補正
    temp_c = temp_850 - 273.15 if np.nanmax(temp_850) > 100 else temp_850
    w700 = w_700 * 3600   # 700hPa鉛直流 [hPa/h]

    lon2d, lat2d = get_lon_lat(temp_850)
    skip = 5

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 700hPa鉛直流 ---
    cf = ax.contourf(
        lon2d, lat2d, w700,
        levels=np.linspace(-20, 20, 21),
        cmap="bwr", extend="both",
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa Vertical Velocity [hPa/h]", fontsize=8)

    # --- 850hPa等温線 ---
    cs = ax.contour(
        lon2d, lat2d, temp_c,
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

    ax.set_title("850hPa温度・風＋700hPa鉛直流", fontsize=11, pad=10)
