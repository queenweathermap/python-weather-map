# ===============================================
# module/plot_850hpa_temp_wind_700hpa_w.py
# 850hPa温度・風＋700hPa鉛直流描画モジュール
# GSM/MSM両対応（引数 model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 利用例:
#   from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds)
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

def plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=None, skip=5):
    """
    850hPa温度・風＋700hPa鉛直流（GSM/MSM両対応）
    """
    lon2d, lat2d = get_lon_lat(ds)

    if model == "GSM":
        temp = ds["TMP_850mb"].values - 273.15  # 850hPa温度 [℃]
        u = ds["UGRD_850mb"].values
        v = ds["VGRD_850mb"].values
        w700 = ds["VVEL_700mb"].values * 3600  # 700hPa鉛直流 [hPa/h]
    elif model == "MSM":
        temp = ds["TMP_850mb"].values - 273.15
        u = ds["UGRD_850mb"].values
        v = ds["VGRD_850mb"].values
        w700 = ds["VVEL_700mb"].values * 3600
    else:
        raise ValueError("model must be 'GSM' or 'MSM'")

    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # 700hPa鉛直流（塗り分け）
    cf = ax.contourf(
        lon2d, lat2d, w700,
        levels=np.linspace(-20, 20, 21),
        cmap="bwr", extend="both",
        transform=ccrs.PlateCarree()
    )
    cbar = plt.colorbar(cf, ax=ax, orientation="vertical", shrink=0.6, pad=0.02)
    cbar.set_label("700hPa鉛直流 [hPa/h]", fontsize=8)

    # 850hPa温度（等温線）
    cs = ax.contour(
        lon2d, lat2d, temp,
        levels=np.arange(-20, 32, 2),
        colors="k", linewidths=0.5,
        transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)

    # 850hPa風ベクトル
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=250, width=0.002, alpha=0.8
    )

    ax.set_title("850hPa温度・風＋700hPa鉛直流", fontsize=10, pad=10, fontproperties=prop)

# ======= ラッパー関数（import用） =======
def plot_850hpa_temp_wind_700hpa_w_gsm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="GSM", prop=prop, skip=skip)

def plot_850hpa_temp_wind_700hpa_w_msm(ax, ds, prop=None, skip=5):
    return plot_850hpa_temp_wind_700hpa_w(ax, ds, model="MSM", prop=prop, skip=skip)

# ===============================================
# END OF FILE
# ===============================================
