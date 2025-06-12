# ===============================================
# module/plot_500hpa_vorticity.py
# 500hPa等高度線＋渦度（正の渦度領域に半透明オレンジ）描画モジュール
# -----------------------------------------------
# 利用例:
#   from module.plot_500hpa_vorticity import plot_500hpa_vorticity_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_500hpa_vorticity_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
import xarray as xr
import metpy.calc as mpcalc
from metpy.units import units

# ======= 共通：緯度経度2次元配列を取得 =======
def get_lon_lat(ds):
    if isinstance(ds, xr.DataArray):
        ds = ds.to_dataset()
    lon = ds["longitude"].values
    lat = ds["latitude"].values
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    else:
        lon2d, lat2d = lon, lat
    return lon2d, lat2d

# ======= 安全に値を取得するヘルパー =======
def _get_var(ds, var):
    if isinstance(ds, xr.DataArray):
        return ds.values
    elif isinstance(ds, xr.Dataset):
        if var in ds.variables:
            return ds[var].values
        elif hasattr(ds, "name") and ds.name == var:
            return ds.values
        else:
            return None
    else:
        return None

def plot_500hpa_vorticity(ax, ds, model="GSM", prop=None):
    """
    500hPa等高度線＋渦度塗りつぶし（GSM/MSM両対応）
    """
    hgt   = _get_var(ds, "HGT_500mb")
    ugrd  = _get_var(ds, "UGRD_500mb")
    vgrd  = _get_var(ds, "VGRD_500mb")
    lon2d, lat2d = get_lon_lat(ds)

    # Noneチェック
    if hgt is None or ugrd is None or vgrd is None:
        raise ValueError("必要な500hPa変数（HGT_500mb/UGRD_500mb/VGRD_500mb）が含まれていません")

    # MetPy単位
    ugrd = ugrd * units('m/s')
    vgrd = vgrd * units('m/s')

    # 格子間隔（平均値）
    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    # 地図・海岸線などの共通描画
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 等高度線（細線＋太線）
    hgt_levels_fine = np.arange(4800, 6001, 60)
    hgt_levels_bold = np.arange(4800, 6001, 120)
    cs = ax.contour(
        lon2d, lat2d, hgt, levels=hgt_levels_fine, colors="navy",
        linewidths=0.8, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)
    ax.contour(
        lon2d, lat2d, hgt, levels=hgt_levels_bold, colors="navy",
        linewidths=2.0, transform=ccrs.PlateCarree()
    )

    # 渦度の正値領域に半透明オレンジ
    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(
        lon2d, lat2d, vorticity_masked,
        levels=[0, 1e-5], colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree()
    )

    ax.set_title("500hPa等高度線・渦度", fontsize=10, pad=10, fontproperties=prop)

# ======= ラッパー関数（import用） =======
def plot_500hpa_vorticity_gsm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="GSM", prop=prop)

def plot_500hpa_vorticity_msm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="MSM", prop=prop)

# ===============================================
# END OF FILE
# ===============================================
