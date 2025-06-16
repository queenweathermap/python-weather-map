# ===============================================
# module/gpv_plotter_msm.py
# MSMモデル用の可視化関数をまとめてimportするモジュール（英語実装＋日本語コメント充実版）
# -----------------------------------------------
# MSM（メソスケールモデル）GPVデータを扱う可視化関数群の一括import用
# - 他スクリプトからは「from module.gpv_plotter_msm import ...」で必要な関数のみ利用可能
# - 描画本体は全て英語化（matplotlib描画部分も含む）
# - 日本語の解説コメントを豊富に追加。運用・引継ぎ・保守も安心
# ===============================================

from .plot_300hpa_height_wind import plot_300hpa_height_wind_msm
from .plot_500hpa_vorticity import plot_500hpa_vorticity_msm
from .plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_msm
from .plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_msm
from .plot_850hpa_thetae_stream import plot_850hpa_thetae_stream_msm
from .plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_msm
from .plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm
from .plot_emagram import plot_emagram_msm_panel

import numpy as np
import matplotlib.pyplot as plt
from metpy.plots import SkewT
from metpy.units import units
import pandas as pd

# ========================================
# MSM用：エマグラム（SkewT/Emagram）描画関数（英語版）
# ----------------------------------------
# ・1地点（緯度経度指定）・1時刻の鉛直プロファイルをエマグラム形式で描画
# ・GSM/その他でも再利用可（次元名や値は共通化推奨）
# ・可視化ラベル、凡例、タイトル等も全て英語で統一
# ========================================
def plot_emagram_msm(fig, col, dsi_point, city_lat, city_lon, city_name, nrows=6, ncols=12):
    """
    Draw an emagram (SkewT plot) for MSM GPV data at a single point.
    - fig: matplotlib Figure instance (multi-panel)
    - col: column index (0-based)
    - nrows, ncols: panel grid shape (default 6x12)
    - dsi_point: xarray DataArray for the specific point (lat/lon/level)
    - city_lat, city_lon: coordinates of the location
    - city_name: city name (string)
    """
    # ---- Create SkewT subplot ----
    skew = SkewT(fig, rotation=0, subplot=(nrows, ncols, 1 + col))

    # ==== 1. Retrieve pressure levels and vertical profiles ====
    pressure_list, temp_list, dewpoint_list = [], [], []
    u_list, v_list, height_list = [], [], []
    # MSM標準レベル
    for level in [1000, 925, 850, 700, 500, 300, 200, 100]:
        pres_key = f"TMP_{level}mb"
        rh_key   = f"RH_{level}mb"
        u_key    = f"UGRD_{level}mb"
        v_key    = f"VGRD_{level}mb"
        hgt_key  = f"HGT_{level}mb"
        try:
            temp = float(dsi_point[pres_key])
            rh   = float(dsi_point[rh_key])
            u    = float(dsi_point[u_key])
            v    = float(dsi_point[v_key])
            hgt  = float(dsi_point[hgt_key]) if hgt_key in dsi_point else np.nan
        except Exception:
            continue  # skip if missing level
        pressure_list.append(level)
        temp_list.append(temp)
        u_list.append(u)
        v_list.append(v)
        height_list.append(hgt)
        # Approximate dewpoint from RH (if no SPFH)
        dewpoint = temp - (100 - rh) / 5  # JMA style approximation
        dewpoint_list.append(dewpoint)

    # ==== 2. Convert to ndarray with units ====
    pressure    = np.array(pressure_list) * units.hPa
    temperature = np.array(temp_list) * units.degC
    dewpoint    = np.array(dewpoint_list) * units.degC
    u_wind      = np.array(u_list) * units.meter / units.second
    v_wind      = np.array(v_list) * units.meter / units.second

    # ==== 3. Draw SkewT/Emagram (English label/legend) ====
    skew.plot(pressure, temperature, 'k', linewidth=1.5, label="T")
    skew.plot(pressure, dewpoint, 'gray', linewidth=1.0, label="Td")
    skew.plot_barbs(pressure, u_wind.to("knots"), v_wind.to("knots"))

    # ==== 4. Show dummy indices (SSI, CAPE, etc.) as placeholder ====
    # （本格的な安定指数計算は後日実装、ここはプレースホルダ）
    ssi_dict = {
        "SHOW": np.nan, "LIFT": np.nan, "SWET": np.nan,
        "KINX": np.nan, "CTOT": np.nan, "VTOT": np.nan,
        "TOTL": np.nan, "CAPE": np.nan, "PWAT": np.nan
    }
    x_text = 45
    y_text = 1020
    dy = 60
    for i, (k, v) in enumerate(ssi_dict.items()):
        val_str = f"{v:.1f}" if not np.isnan(v) else "---"
        skew.ax.text(x_text, y_text - i * dy, f"{k}: {val_str}", fontsize=8, ha='left', va='top')

    # ==== 5. Location/Time annotation (English) ====
    try:
        tstr = pd.to_datetime(dsi_point['time'].values).strftime('%Y-%m-%d %HZ')
    except Exception:
        tstr = ""
    skew.ax.set_title(f"{city_name} ({city_lat:.2f}, {city_lon:.2f})\n{tstr}", loc='left', fontsize=9)

    # ==== 6. Axis/limits and grid style (English) ====
    skew.ax.set_ylim(1050, 100)
    skew.ax.set_xlim(-40, 40)
    skew.ax.grid(True, which='major', color='gray', linestyle='--', alpha=0.5)

    # ==== 7. Legend (English) ====
    skew.ax.legend(fontsize=7, loc="upper right")

    return skew.ax

# ===============================================
