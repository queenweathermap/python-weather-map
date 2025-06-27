# ===============================================
# module/plot/plot_emagram.py
# エマグラム（気温・露点温度・風バーブ）描画モジュール
# plot_emagram(ax, ds, step=0, lat=39.72, lon=140.10)
# -----------------------------------------------
# 2025-06-26 ChatGPT リファクタ・シグネチャ統一
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
from metpy.plots import SkewT
from metpy.units import units
from module.utils.var_utils import get_var

from module.plot.plot_utils import set_japanese_font, plot_no_data_japan_map
set_japanese_font()  # 日本語フォントを全描画で有効化

def extract_profile_gpv(ds, lat, lon, time_idx=0):
    """
    指定緯度・経度・時刻インデックスの鉛直プロファイル（気温・露点・風）抽出
    """
    lat_arr = get_var(ds, "latitude")
    lon_arr = get_var(ds, "longitude")
    ilat = np.abs(lat_arr - lat).argmin()
    ilon = np.abs(lon_arr - lon).argmin()
    levels = []
    temp = []
    dew = []
    u = []
    v = []
    for level in [1000, 925, 850, 700, 500, 300, 200, 100]:
        key_tmp = f"TMP_{level}mb"
        key_rh = f"RH_{level}mb"
        key_u = f"UGRD_{level}mb"
        key_v = f"VGRD_{level}mb"
        t_arr = get_var(ds, key_tmp)
        rh_arr = get_var(ds, key_rh)
        u_arr = get_var(ds, key_u)
        v_arr = get_var(ds, key_v)
        if t_arr is not None and rh_arr is not None:
            t = t_arr[time_idx, ilat, ilon] - 273.15  # K→℃
            rh = rh_arr[time_idx, ilat, ilon]
            td = t - (100 - rh) / 5  # 簡易近似
            temp.append(t)
            dew.append(td)
            levels.append(level)
            u.append(u_arr[time_idx, ilat, ilon] if u_arr is not None else np.nan)
            v.append(v_arr[time_idx, ilat, ilon] if v_arr is not None else np.nan)
    if not levels:
        return np.array([]), np.array([]), np.array([]), np.array([]), np.array([])
    idx = np.argsort(levels)[::-1]
    return (
        np.array(levels)[idx],
        np.array(temp)[idx],
        np.array(dew)[idx],
        np.array(u)[idx],
        np.array(v)[idx],
    )

def plot_emagram(ax, ds, step=0, lat=39.72, lon=140.10):
    """
    エマグラム（SkewT）を1コマ描画
    Parameters
    ----------
    ax : matplotlib.axes.Axes
        描画先
    ds : xarray.Dataset
        データセット
    step : int, default 0
        ds.timeのインデックス
    lat, lon : float
        プロファイル抽出位置
    Returns
    -------
    None
    """
    time_idx = step
    levels, temp, dew, u, v = extract_profile_gpv(ds, lat, lon, time_idx=time_idx)
    if len(levels) == 0:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
        ax.set_axis_off()
        return

    p = levels * units.hPa
    t = temp * units.degC
    td = dew * units.degC

    skew = SkewT(ax, rotation=45)
    skew.plot(p, t, 'r')
    skew.plot(p, td, 'g')
    skew.ax.set_ylim(1000, 100)
    skew.ax.set_xlim(-50, 40)
    skew.ax.set_xlabel('Temperature (°C)')
    skew.ax.set_ylabel('Pressure (hPa)')
    skew.ax.set_title(f'Emagram\nLat: {lat:.2f}, Lon: {lon:.2f}', fontsize=10, pad=10)

    # 風バーブ
    if u is not None and v is not None:
        skew.plot_barbs(p, u, v)

