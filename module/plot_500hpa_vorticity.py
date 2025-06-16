# ===============================================
# module/plot_500hpa_vorticity.py
# 500hPa等高度線＋渦度（正の渦度領域に半透明オレンジ）描画モジュール
# GSM/MSM両対応
# -----------------------------------------------
# 利用例:
#   from module.plot_500hpa_vorticity import plot_500hpa_vorticity_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_500hpa_vorticity_gsm(ax, ds)
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


def get_lon_lat(ds):
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_500hpa_vorticity(ax, ds, model="GSM", prop=None):
    """
    500hPa等高度線＋渦度（正の渦度領域オレンジ塗り）描画（GSM/MSM両対応）
    """
    import metpy.calc as mpcalc
    from metpy.units import units

    hgt   = get_var(ds, "HGT_500mb")
    ugrd  = get_var(ds, "UGRD_500mb") * units('m/s')
    vgrd  = get_var(ds, "VGRD_500mb") * units('m/s')
    lon2d, lat2d = get_lon_lat(ds)

    # --- メトピー流の格子間隔を計算 ---
    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 等高度線 ---
    cs = ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60),
                    colors="navy", linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120),
               colors="navy", linewidths=2.0, transform=ccrs.PlateCarree())

    # --- 渦度（正の値のみ半透明オレンジ） ---
    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(lon2d, lat2d, vorticity_masked, levels=[0, 1e-5],
                colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree())

    ax.set_title("500hpa_vorticity", fontsize=10, pad=10, fontproperties=prop)

# ======= ラッパー関数 =======
def plot_500hpa_vorticity_gsm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="GSM", prop=prop)

def plot_500hpa_vorticity_msm(ax, ds, prop=None):
    return plot_500hpa_vorticity(ax, ds, model="MSM", prop=prop)

# ===============================================
# END OF FILE
# ===============================================
