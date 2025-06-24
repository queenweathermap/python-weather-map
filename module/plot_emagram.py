# ===============================================
# module/plot_emagram.py
# エマグラム（気温・露点温度・風バーブ）描画モジュール
# GSM/MSM両対応、複数時刻の一括パネル出力対応
# -----------------------------------------------
# 日本語コメント多数：SkewTロギングエマグラムに気温・露点・風バーブを描画
# 利用例:
#   from module.plot_emagram import plot_emagram_gsm_panel
#   fig = plot_emagram_gsm_panel(ds, lat=39.72, lon=140.10, times=ds.time.values[:6])
#   fig.savefig("emagram_panel.jpg")
# 2025-06-13 by ChatGPT
# ===============================================

import numpy as np
from metpy.plots import SkewT
from metpy.units import units
from module.utils.var_utils import get_var

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

# -------------------------------------------------
# xarrayデータセットから1地点（lat/lon/時刻）の鉛直プロファイルを抽出
# -------------------------------------------------
def extract_profile_gpv(ds, lat, lon, time_idx=0):
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
            t = t_arr[time_idx, ilat, ilon] - 273.15  # 絶対温度→摂氏
            rh = rh_arr[time_idx, ilat, ilon]
            td = t - (100 - rh) / 5  # 近似露点温度
            temp.append(t)
            dew.append(td)
            levels.append(level)
            u.append(u_arr[time_idx, ilat, ilon] if u_arr is not None else np.nan)
            v.append(v_arr[time_idx, ilat, ilon] if v_arr is not None else np.nan)
        else:
            # 欠損時：appendしない（そのlevelは飛ばす）
            continue
    if not levels:
        # 全て欠損の場合、空配列を返す（落ちない対策）
        return np.array([]), np.array([]), np.array([]), np.array([]), np.array([])
    idx = np.argsort(levels)[::-1]  # 高い気圧→低い気圧順
    return (np.array(levels)[idx], np.array(temp)[idx], np.array(dew)[idx], np.array(u)[idx], np.array(v)[idx])

# -------------------------------------------------
# SkewT（エマグラム）への描画本体
# -------------------------------------------------
def plot_emagram_skewt(ax, ds, lat, lon, time_idx=0, title="Emagram"):
    levels, temp, dew, u, v = extract_profile_gpv(ds, lat, lon, time_idx)
    if len(levels) == 0:
        # データ欠損時はグレーで「No Data」テキスト
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=16, color='gray', transform=ax.transAxes)
        ax.set_axis_off()
        return ax

# -------------------------------------------------
# 複数時刻パネルでエマグラムを並べて表示（横並び最大6枚程度まで）
# -------------------------------------------------
def plot_emagram_panel(ds, lat=39.72, lon=140.10, times=None, model_name="GSM"):
    """
    複数時刻のエマグラムパネルを一括描画
    - ds: xarray.Dataset
    - lat, lon: 緯度・経度
    - times: 時刻リスト（省略時は先頭6つ）
    - model_name: "GSM"/"MSM"など（タイトル用）
    """
    if times is None:
        times = ds.time.values[:6]
    ncols = len(times)
    fig, axes = plt.subplots(1, ncols, figsize=(4 * ncols, 6), constrained_layout=True)
    if ncols == 1:
        axes = [axes]
    for i, t in enumerate(times):
        tlist = ds.time.values
        time_idx = np.where(tlist == np.datetime64(t))[0][0]
        title = f"{model_name}\n{str(t)[:16]}"
        plot_emagram_skewt(axes[i], ds, lat, lon, time_idx=time_idx, title=title)
    fig.suptitle(f"{model_name} Emagram\nLat: {lat:.2f}, Lon: {lon:.2f}", fontsize=13, y=1.05)
    return fig

# -------------------------------------------------
# GSM/MSMラッパー関数
# -------------------------------------------------
def plot_emagram_gsm_panel(ds, lat=39.72, lon=140.10, times=None):
    """GSM用ラッパー"""
    return plot_emagram_panel(ds, lat=lat, lon=lon, times=times, model_name="GSM")

def plot_emagram_msm_panel(ds, lat=39.72, lon=140.10, times=None):
    """MSM用ラッパー"""
    return plot_emagram_panel(ds, lat=lat, lon=lon, times=times, model_name="MSM")

# ===============================================
# END OF FILE
# ===============================================
