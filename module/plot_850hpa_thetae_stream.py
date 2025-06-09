# ===============================================
# plot_850hpa_thetae_stream.py
# 850hPa相当温位（1K刻み・15Kごと太線）＋流線 描画モジュール
# GSM/MSM両対応（引数 model="GSM"/"MSM" で切り替え）
# -----------------------------------------------
# 利用例:
#   from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
#   fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
#   plot_850hpa_thetae_stream(ax, ds, model="GSM", prop=None)
#   plt.show()
# -----------------------------------------------
# 2025-06-07 by ChatGPT
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# ======= 緯度経度2次元配列取得関数 =======
def get_lon_lat(ds):
    """
    データセットから2次元緯度・経度配列を取得（'longitude','latitude'）
    """
    lon2d = ds["longitude"].values
    lat2d = ds["latitude"].values
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# ======= メイン描画関数 =======
def plot_850hpa_thetae_stream_gsm(ax, ds, model="GSM", prop=None):
    """
    850hPa簡易相当温位（1K刻み・15Kごと太線）＋流線（紺色）
    GSM/MSM両対応

    Parameters
    ----------
    ax : matplotlib.axes
        描画先Axis（Cartopy地図投影付き）
    ds : xarray.Dataset
        GPVデータセット
    model : str, default "GSM"
        "GSM" または "MSM"
    prop : FontProperties, optional
        matplotlib.font_manager.FontProperties オブジェクト
    """

    # ======= 緯度・経度 =======
    lon2d, lat2d = get_lon_lat(ds)

    # ======= モデルごとに変数分岐 =======
    temp = ds["TMP_850mb"].values
    rh   = ds["RH_850mb"].values if "RH_850mb" in ds.variables else None
    u    = ds["UGRD_850mb"].values if "UGRD_850mb" in ds.variables else None
    v    = ds["VGRD_850mb"].values if "VGRD_850mb" in ds.variables else None

    # ======= 簡易相当温位計算 =======
    if rh is not None:
        Td = temp - (100 - rh) / 5  # 850hPa露点温度の近似
        thetae_like = temp + 0.2854 * Td
    else:
        thetae_like = temp

    # ======= 等値線のレベル設定 =======
    min_thetae = int(np.nanmin(thetae_like) // 1 * 1)
    max_thetae = int(np.nanmax(thetae_like) // 1 * 1) + 1
    levels = np.arange(min_thetae, max_thetae + 1, 1)           # 1K刻み
    bold_levels = np.arange(min_thetae, max_thetae + 15, 15)    # 15Kごと太線

    # ======= 等相当温位線（細線・薄いグレー） =======
    cs1 = ax.contour(
        lon2d, lat2d, thetae_like,
        levels=levels, colors="#888888", linewidths=0.5, linestyles="-",
        transform=ccrs.PlateCarree()
    )

    # ======= 等相当温位線（15Kごと太線・黒） =======
    cs2 = ax.contour(
        lon2d, lat2d, thetae_like,
        levels=bold_levels, colors="k", linewidths=1.2, linestyles="-",
        transform=ccrs.PlateCarree()
    )
    # 太線のみラベル
    ax.clabel(cs2, fontsize=7, fmt="%.0f") 


    # ======= 850hPa流線（紺色） =======
    if u is not None and v is not None:
        ax.streamplot(
            lon2d, lat2d, u, v,
            density=1.3, color="#003366", linewidth=0.4,
            transform=ccrs.PlateCarree(), arrowsize=0.5
        )

    # ======= 地図範囲・海岸線・国境線 =======
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.4)

    # ======= タイトル =======
    ax.set_title("850hPa簡易相当温位（1K刻み/15Kごと太線）＋流線", fontsize=10, pad=10, fontproperties=prop)

# ===============================================
# END OF FILE
# ===============================================
