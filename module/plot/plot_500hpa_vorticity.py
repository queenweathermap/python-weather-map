# ===============================================
# module/plot/plot_500hpa_vorticity.py
# 500hPa Geopotential Height + Positive Vorticity Area
# ===============================================

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



def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# module/plot/plot_500hpa_vorticity.py
def plot_500hpa_vorticity(ax, ds_dict, step=0):
    """
    500hPa等高度・正渦度（オレンジ）パネル描画（dict＋step対応/完全2次元化/np.ndarray渡しで安全）
    ds_dict: {"h":..., "u":..., "v":...}
    step: スライス番号
    """
    import numpy as np
    import metpy.calc as mpcalc
    from metpy.units import units

    # --- NO DATAチェック ---
    for k in ["h", "u", "v"]:
        arr = ds_dict.get(k)
        if arr is None or "step" not in arr.dims or step >= arr.sizes["step"]:
            ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
            ax.coastlines(resolution="50m")
            ax.add_feature(cfeature.BORDERS, linestyle=":")
            ax.text(0.5, 0.5, f"NO DATA\n({k})", fontsize=14, color="gray",
                    ha="center", va="center", transform=ax.transAxes)
            return

    # --- step, time, valid_time すべて落とし "y, x" だけに ---
    def arr2d(da):
        # da: xarray.DataArray
        # 必要な次元は latitude/longitude または (y, x) だけ
        sl = {}
        for dim in da.dims:
            if dim == "step":
                sl[dim] = step
            elif dim in ["time", "valid_time"]:
                sl[dim] = 0
        da2 = da.isel(**sl) if sl else da
        return da2.values  # ndarrayで返す

    hgt  = arr2d(ds_dict["h"])
    ugrd = arr2d(ds_dict["u"])
    vgrd = arr2d(ds_dict["v"])

    # --- 格子生成 ---
    lon = ds_dict["h"]["longitude"]
    lat = ds_dict["h"]["latitude"]
    lon2d = lon.values
    lat2d = lat.values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)

    # --- 渦度計算（np.ndarray + metpy units）---
    ugrd = ugrd * units('m/s')
    vgrd = vgrd * units('m/s')
    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    # --- 地図装飾 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 等高度線 ---
    cs = ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60),
                    colors="navy", linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120),
               colors="navy", linewidths=2.0, transform=ccrs.PlateCarree())

    # --- 正渦度のみマスクして塗る ---
    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(lon2d, lat2d, vorticity_masked, levels=[0, 1e-5],
                colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree())

    ax.set_title("500hPa渦度", fontsize=10, pad=10)
