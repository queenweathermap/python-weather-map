# ===============================================
# module/gpv_plotter_msm.py
# MSMモデル用の可視化関数をまとめてimportするモジュール
# 他のスクリプトからは「from module.gpv_plotter_msm import ...」で
# 必要な描画関数を一括で使えるようにします。
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
# MSM用：エマグラム（SkewT/Emagram）描画関数
# ========================================
def plot_emagram_msm(fig, col, dsi_point, city_lat, city_lon, city_name, nrows=6, ncols=12):
    """
    MSM GPVデータからエマグラムを描画（マルチパネル対応）
    fig : matplotlib Figure（必須）
    col : パネルの列番号（0起点）
    nrows, ncols : パネルの行数・列数（デフォルト6x12）
    dsi_point : xarray DataArray（lat/lon=ピンポイント or level次元付き）
    city_lat, city_lon : 地点情報
    city_name : 地名（例：秋田）
    """
    # ---- SkewTサブプロット生成 ----
    skew = SkewT(fig, rotation=0, subplot=(nrows, ncols, 1 + col))

    # ==== 1. 気圧面リスト・鉛直データを自動取得 ====
    pressure_list = []
    temp_list = []
    dewpoint_list = []
    u_list = []
    v_list = []
    height_list = []
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
            continue  # その面がなければskip
        pressure_list.append(level)
        temp_list.append(temp)
        u_list.append(u)
        v_list.append(v)
        height_list.append(hgt)
        # 露点温度（RH→dewpoint計算。SPFHしかない場合は工夫が要る）
        dewpoint = temp - (100 - rh) / 5  # 近似（気象庁式）
        dewpoint_list.append(dewpoint)

    # ==== 2. ndarray, unitsつきで変換 ====
    pressure    = np.array(pressure_list) * units.hPa
    temperature = np.array(temp_list) * units.degC
    dewpoint    = np.array(dewpoint_list) * units.degC
    u_wind      = np.array(u_list) * units.meter / units.second
    v_wind      = np.array(v_list) * units.meter / units.second

    # ==== 3. SkewT（エマグラム）描画 ====
    skew.plot(pressure, temperature, 'k', linewidth=1.5, label="T")
    skew.plot(pressure, dewpoint, 'gray', linewidth=1.0, label="Td")
    skew.plot_barbs(pressure, u_wind.to("knots"), v_wind.to("knots"))

    # ==== 4. SSI等（安定指数）を計算して右にテキストで追記 ====
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

    # ==== 5. 地点・時刻情報 ====
    try:
        tstr = pd.to_datetime(dsi_point['time'].values).strftime('%Y-%m-%d %HZ')
    except Exception:
        tstr = ""
    skew.ax.set_title(f"{city_name} ({city_lat:.2f}, {city_lon:.2f})\n{tstr}", loc='left', fontsize=9)

    # ==== 6. 軸範囲など調整 ====
    skew.ax.set_ylim(1050, 100)
    skew.ax.set_xlim(-40, 40)
    skew.ax.grid(True, which='major', color='gray', linestyle='--', alpha=0.5)

    # ==== 7. 装飾 ====
    skew.ax.legend(fontsize=7, loc="upper right")

    return skew.ax
