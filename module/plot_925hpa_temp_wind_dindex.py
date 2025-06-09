# ===============================================
# plot_925hpa_temp_wind_dindex.py
# 925hPa温度・風・湿数描画モジュール（GSM/MSM両対応）
# -----------------------------------------------
# 利用例:
#   from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_925hpa_temp_wind_dindex_gsm(ax, ds)
#   plt.show()
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

def get_lon_lat(ds):
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

def plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=None, skip=5):
    lon2d, lat2d = get_lon_lat(ds)
    # データ取得
    temp = ds["TMP_925mb"].values - 273.15  # 925hPa温度
    u = ds["UGRD_925mb"].values
    v = ds["VGRD_925mb"].values
    rh = ds["RH_925mb"].values
    # 湿数計算（露点温度の近似）
    dewpoint = temp - (100 - rh) / 5
    dindex = temp - dewpoint

    # 地図描画
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 温度等値線
    cs_temp = ax.contour(lon2d, lat2d, temp, levels=np.arange(-20, 36, 2), colors="k", linewidths=0.7, transform=ccrs.PlateCarree())
    ax.clabel(cs_temp, fontsize=6)
    # 湿数塗り分け
    cf = ax.contourf(lon2d, lat2d, dindex, levels=np.linspace(0, 30, 13), cmap="Greens", alpha=0.6, transform=ccrs.PlateCarree())
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("925hPa湿数 [℃]", fontsize=8)
    # 風ベクトル
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.7
    )

    ax.set_title("925hPa温度・風・湿数", fontsize=10, pad=10, fontproperties=prop)

def plot_925hpa_temp_wind_dindex_gsm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_925hpa_temp_wind_dindex_msm(ax, ds, prop=None, skip=5):
    return plot_925hpa_temp_wind_dindex(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
