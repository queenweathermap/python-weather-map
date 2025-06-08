# ===============================================
# plot_500hPa_vorticity.py
# 500hPa等高度線＋渦度（正の渦度領域に半透明オレンジ）描画モジュール
# -----------------------------------------------
# 利用例:
#   from module.plot_500hPa_vorticity import plot_500hpa_vorticity
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_500hpa_vorticity(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter
from metpy.calc import vorticity
from metpy.units import units

# ======= 緯度経度2次元配列取得関数 =======
def get_lon_lat(ds):
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# ======= メイン描画関数 =======
def plot_500hpa_vorticity(ax, ds, prop=None):
    """
    500hPa等高度線＋渦度塗りつぶしの描画（格子間隔は平均値使用でshapeエラー回避）
    """
    import metpy.calc as mpcalc
    from metpy.units import units
    import numpy as np
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    # --- データ取得 ---
    hgt   = ds["HGT_500mb"].values
    ugrd  = ds["UGRD_500mb"].values * units('m/s')
    vgrd  = ds["VGRD_500mb"].values * units('m/s')
    lon2d, lat2d = get_lon_lat(ds)

    # --- dx, dyの計算（緯度経度格子→m単位）---
    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)

    # --- 平均値を使えばshapeズレしない！ ---
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)

    # --- 渦度計算（u, v, 平均dx/dy）---
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    # --- 形状確認 ---
    print("=== SHAPE CHECK ===")
    print("u :", ugrd.shape)
    print("v :", vgrd.shape)
    print("dx_mean :", dx_mean)
    print("dy_mean :", dy_mean)
    print("vort:", vort.shape)
    print("lon2d:", lon2d.shape)
    print("lat2d:", lat2d.shape)

    # --- 地図枠 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 500hPa等高度線 ---
    cs = ax.contour(
        lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60), colors="navy",
        linewidths=0.8, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)
    ax.contour(
        lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120), colors="navy",
        linewidths=2.0, transform=ccrs.PlateCarree()
    )

    # --- 渦度（0以上をオレンジで塗る例）---
    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(
        lon2d, lat2d, vorticity_masked,
        levels=[0, 1e-5], colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree()
    )

    # --- タイトル ---
    ax.set_title("500hPa等高度線・渦度", fontsize=10, pad=10, fontproperties=prop)


# ===============================================
# END OF FILE
# ===============================================