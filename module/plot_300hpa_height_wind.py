# ===============================================
# module/plot_300hpa_height_wind.py
# 300hPa等高度線＋等風速線＋風ベクトル描画モジュール
# GSM/MSM両対応（引数 model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 利用方法例:
#   from module.plot_300hpa_height_wind import plot_300hpa_height_wind_gsm
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_300hpa_height_wind_gsm(ax, ds)
#   plt.show()
# -----------------------------------------------
# 2025-06-07 by ChatGPT
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.ndimage import maximum_filter, minimum_filter

# ======= 共通：緯度経度2次元配列を取得 =======
def get_lon_lat(ds):
    """
    データセットから2次元緯度・経度配列を取得（変数名は'ds["longitude"]', 'ds["latitude"]'）
    """
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    # 1次元ならmeshgridで2次元に
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# ======= メイン描画関数 =======
def plot_300hpa_height_wind(ax, ds, model="GSM", skip=5):
    import xarray as xr

    lon2d, lat2d = get_lon_lat(ds)

    # ======= モデルごとに変数名などを分岐 =======
    def _get_var(ds, var):
        # dsがDatasetならキーで取り出す/DataArrayならそのまま返す
        if isinstance(ds, xr.Dataset):
            return ds[var].values if var in ds.variables else None
        elif isinstance(ds, xr.DataArray):
            return ds.values
        else:
            return None


    hgt = _get_var(ds, "HGT_300mb")
    u   = _get_var(ds, "UGRD_300mb")
    v   = _get_var(ds, "VGRD_300mb")
    temp = _get_var(ds, "TMP_300mb")

    if hgt is None or u is None or v is None:
        raise ValueError("必要な300hPa変数が含まれていません")

    # 風速（ノットに換算）
    wspd = np.sqrt(u**2 + v**2) * 1.94384



    # ======= 地図・海岸線などの共通描画 =======
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # ======= （オプション）等温線 =======
    if temp is not None:
        temp_c = temp - 273.15 if np.nanmax(temp) > 100 else temp  # K→℃
        t_levels = np.arange(-60, 6, 6)
        cs_temp = ax.contour(
            lon2d, lat2d, temp_c, levels=t_levels,
            colors='blue', linewidths=0.8, linestyles='dashed',
            transform=ccrs.PlateCarree()
        )
        ax.clabel(cs_temp, fmt="%.0f", fontsize=7, colors="blue")

    # ======= 等高度線（細線＋太線） =======
    hgt_levels = np.arange(9600, 16001, 120)
    cs = ax.contour(
        lon2d, lat2d, hgt, levels=hgt_levels, colors="navy",
        linewidths=0.8, transform=ccrs.PlateCarree()
    )
    ax.clabel(cs, fontsize=6)
    bold_lv = np.arange(9600, 16001, 240)
    bold = ax.contour(
        lon2d, lat2d, hgt, levels=bold_lv, colors="navy",
        linewidths=2.0, transform=ccrs.PlateCarree()
    )

    # ======= 等風速線 =======
    ws_levels = np.arange(20, 180, 20)
    ws = ax.contour(
        lon2d, lat2d, wspd, levels=ws_levels,
        colors="gray", linestyles="solid", linewidths=0.5,
        transform=ccrs.PlateCarree()
    )
    ax.clabel(ws, fmt="%d", fontsize=7, colors="black")
    # 東風のみ（波線）
    for level in ws_levels:
        wspd_east = np.where(u < 0, wspd, np.nan)
        cs_east = ax.contour(
            lon2d, lat2d, wspd_east, levels=[level],
            colors="gray", linestyles="dashed", linewidths=0.7,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(cs_east, fmt="%d", fontsize=7, colors="black")

    # ======= 風ベクトル（透明度80%） =======
    ax.quiver(
        lon2d[::skip, ::skip], lat2d[::skip, ::skip],
        u[::skip, ::skip], v[::skip, ::skip],
        transform=ccrs.PlateCarree(), scale=350, alpha=0.3
    )

    # ======= 高度場の極値検出・H/Lマーク =======
    hgt_max = maximum_filter(hgt, size=9)
    hgt_min = minimum_filter(hgt, size=9)
    hgt_flat = hgt.flatten()
    hmax_indices = np.argpartition(hgt_flat, -2)[-2:]
    hmin_indices = np.argpartition(hgt_flat, 2)[:2]
    hmax_coords = np.unravel_index(hmax_indices, hgt.shape)
    hmin_coords = np.unravel_index(hmin_indices, hgt.shape)
    for j, i in zip(*hmax_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
    for j, i in zip(*hmin_coords):
        ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    # ======= W/Cマーク（気温：最大3か所ずつ） =======
    if temp is not None:
        temp_flat = temp.flatten()
        w_indices = np.argpartition(temp_flat, -3)[-3:]
        c_indices = np.argpartition(temp_flat, 3)[:3]
        w_coords = np.unravel_index(w_indices, temp.shape)
        c_coords = np.unravel_index(c_indices, temp.shape)
        for j, i in zip(*w_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'W', color='red', fontsize=13, weight='bold', ha='center', va='center')
        for j, i in zip(*c_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'C', color='blue', fontsize=13, weight='bold', ha='center', va='center')

    # ======= タイトル =======
    ax.set_title("300hPa等高度線・風", fontsize=10, pad=10)

# ======= ラッパー関数 =======
def plot_300hpa_height_wind_gsm(ax, ds):
    return plot_300hpa_height_wind(ax, ds, model="GSM")

def plot_300hpa_height_wind_msm(ax, ds):
    return plot_300hpa_height_wind(ax, ds, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
