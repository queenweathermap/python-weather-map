# ===============================================
# module/plot/plot_surface_pressure_wind_precip.py
# 地上海面更正気圧・風 描画モジュール（降水量なし）
# plot_surface_pressure_and_wind_msm(ax, ds_dict, step=0)
# -----------------------------------------------
# 2025-07-05 ChatGPT リファクタ（降水量完全カット）
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from module.utils.var_utils import get_var
from module.plot.plot_utils import set_japanese_font, plot_no_data_japan_map
set_japanese_font()  # 日本語フォントを全描画で有効化

def plot_surface_pressure_and_wind_msm(ax, ds_dict, step=0):
    """
    地上海面更正気圧・風のみ描画（降水量は描画しません）
    ds_dict: {"prmsl":..., "u10":..., "v10":...}
    """
    prmsl = ds_dict.get("prmsl")
    u10   = ds_dict.get("u10")
    v10   = ds_dict.get("v10")

    # step次元がある場合だけスライス
    if prmsl is not None and "step" in prmsl.dims:
        prmsl = prmsl.isel(step=step)
    if u10 is not None and "step" in u10.dims:
        u10 = u10.isel(step=step)
    if v10 is not None and "step" in v10.dims:
        v10 = v10.isel(step=step)

    # 緯度経度をprmsl/u10/v10のどれかから取得
    lon2d, lat2d = None, None
    for arr in [prmsl, u10, v10]:
        if arr is not None:
            lon2d = arr["longitude"].values
            lat2d = arr["latitude"].values
            if lon2d.ndim == 1 and lat2d.ndim == 1:
                lon2d, lat2d = np.meshgrid(lon2d, lat2d)
            break

    # 地図装飾
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS, linestyle=":")

    has_content = False

    # --- 海面更正気圧（等圧線） ---
    if prmsl is not None and lon2d is not None:
        prmsl_hpa = prmsl / 100  # [hPa]
        levels_fine = np.arange(900, 1101, 1)
        cs = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_fine, colors='k', linewidths=0.6,
            transform=ccrs.PlateCarree()
        )
        levels_bold = np.arange(900, 1101, 4)
        cs_bold = ax.contour(
            lon2d, lat2d, prmsl_hpa,
            levels=levels_bold, colors='k', linewidths=2.0,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(cs, fmt="%.0f", fontsize=6)
        label_texts = ax.clabel(cs_bold, fmt="%.0f", fontsize=8, colors='k')
        for txt in label_texts:
            txt.set_fontweight('bold')
        has_content = True

        # H/Lマーク
        prmsl_flat = prmsl_hpa.values.flatten()
        hmax_indices = np.argpartition(prmsl_flat, -2)[-2:]
        hmin_indices = np.argpartition(prmsl_flat, 2)[:2]
        hmax_coords = np.unravel_index(hmax_indices, prmsl_hpa.shape)
        hmin_coords = np.unravel_index(hmin_indices, prmsl_hpa.shape)
        for j, i in zip(*hmax_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'H', color='blue', fontsize=14, weight='bold', ha='center', va='center')
        for j, i in zip(*hmin_coords):
            ax.text(lon2d[j, i], lat2d[j, i], 'L', color='red', fontsize=14, weight='bold', ha='center', va='center')

    # --- 10m風ベクトル ---
    if u10 is not None and v10 is not None and lon2d is not None:
        skip = 5
        ax.quiver(
            lon2d[::skip, ::skip], lat2d[::skip, ::skip],
            u10[::skip, ::skip], v10[::skip, ::skip],
            transform=ccrs.PlateCarree(), scale=500, width=0.002, alpha=0.8
        )
        has_content = True

    # --- 全部なければNO DATA ---
    if not has_content:
        ax.text(0.5, 0.5, "NO DATA", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
        ax.set_axis_off()

    # タイトル
    title = "地上気圧・風"
    ax.set_title(f"{title} (+{step}h)", fontsize=10, pad=10)
