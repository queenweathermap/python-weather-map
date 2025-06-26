# ===============================================
# module/plot_500hpa_vorticity.py
# 500hPa Geopotential Height + Positive Vorticity Area (Orange fill)
# -----------------------------------------------
# 機能概要:
#   - 500hPa等高度線の描画
#   - 正の渦度領域を半透明オレンジで塗り分け
#   - H/Lマークや拡張も容易
#   - GSM/MSMどちらにも使える汎用設計
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

# -------------------------------------------------
# 緯度経度グリッドをxarray.Datasetから抽出する関数
# -------------------------------------------------
def get_lon_lat(ds):
    """
    xarray.Datasetから2次元lon/lat配列を生成
    """
    lon2d = np.asarray(ds["longitude"])
    lat2d = np.asarray(ds["latitude"])
    if lon2d.ndim == 1 and lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lon2d, lat2d

# -------------------------------------------------
# 500hPaパネル描画のメイン関数
# -------------------------------------------------
def plot_500hpa_vorticity(ax, ds, model="GSM", prop=None):
    """
    Plot 500hPa geopotential height (contour) and positive vorticity area (orange fill).
    (日本語解説: 500hPa等高度線＋正の渦度領域をオレンジで塗り分け)
    - ax: matplotlib axes (with PlateCarree projection)
    - ds: xarray.Dataset
    - model: "GSM" or "MSM"
    - prop: フォント設定（任意）
    """
    import metpy.calc as mpcalc
    from metpy.units import units

    hgt   = get_var(ds, "HGT_500mb")
    ugrd  = get_var(ds, "UGRD_500mb")
    vgrd  = get_var(ds, "VGRD_500mb")

    # ---- テスト用途: 欠損時はスキップ、エラー回避 ----
    if hgt is None or ugrd is None or vgrd is None:
        print("[WARN] 500hPaの必要変数がありません（hgt/ugrd/vgrd）→空描画")
        return  # ※描画せず抜ける

    # (MSMだと片方しか無いケースがある)
    ugrd = ugrd * units('m/s')
    vgrd = vgrd * units('m/s')
    lon2d, lat2d = get_lon_lat(ds)


    # --- メトピー流の格子間隔（m単位）を計算 ---
    dy, dx = mpcalc.lat_lon_grid_deltas(lon2d, lat2d)
    dx_mean = np.mean(dx)
    dy_mean = np.mean(dy)
    # --- 渦度計算（中央差分）---
    vort = mpcalc.vorticity(ugrd, vgrd, dx=dx_mean, dy=dy_mean)

    # --- 地図の範囲・海岸線 ---
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    # --- 等高度線 ---
    cs = ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 60),
                    colors="navy", linewidths=0.8, transform=ccrs.PlateCarree())
    ax.clabel(cs, fontsize=6)
    ax.contour(lon2d, lat2d, hgt, levels=np.arange(4800, 6001, 120),
               colors="navy", linewidths=2.0, transform=ccrs.PlateCarree())

    # --- 渦度: 正の値だけ半透明オレンジで塗りつぶし ---
    vorticity_masked = np.ma.masked_less_equal(vort, 0)
    ax.contourf(lon2d, lat2d, vorticity_masked, levels=[0, 1e-5],
                colors=["orange"], alpha=0.5, transform=ccrs.PlateCarree())

    # --- タイトル（フォントプロパティ付与可） ---
    ax.set_title("500hPa Vorticity", fontsize=10, pad=10, fontproperties=prop)

# -------------------------------------------------
# ラッパー関数（GSM/MSM両対応でimportしやすく）
# -------------------------------------------------
def plot_500hpa_vorticity_gsm(ax, ds, prop=None):
    """GSM向け500hPa渦度描画ラッパー"""
    return plot_500hpa_vorticity(ax, ds, model="GSM", prop=prop)

def plot_500hpa_vorticity_msm(ax, ds, prop=None):
    """MSM向け500hPa渦度描画ラッパー"""
    return plot_500hpa_vorticity(ax, ds, model="MSM", prop=prop)

# ===============================================
# END OF FILE
# ===============================================
