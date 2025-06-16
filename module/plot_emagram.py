# ===============================================
# module/plot_emagram.py
# エマグラム（気温・露点温度・風バーブ）描画モジュール
# GSM/MSM両対応、複数時刻の一括パネル出力対応
# -----------------------------------------------
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
            t = t_arr[time_idx, ilat, ilon] - 273.15
            rh = rh_arr[time_idx, ilat, ilon]
            td = t - (100 - rh) / 5
            temp.append(t)
            dew.append(td)
            levels.append(level)
            u.append(u_arr[time_idx, ilat, ilon] if u_arr is not None else np.nan)
            v.append(v_arr[time_idx, ilat, ilon] if v_arr is not None else np.nan)
    idx = np.argsort(levels)[::-1]
    return (np.array(levels)[idx], np.array(temp)[idx], np.array(dew)[idx], np.array(u)[idx], np.array(v)[idx])

def plot_emagram_skewt(ax, ds, lat, lon, time_idx=0, title="Emagram"):
    levels, temp, dew, u, v = extract_profile_gpv(ds, lat, lon, time_idx)
    p = levels * units.hPa
    t = temp * units.degC
    td = dew * units.degC
    u = u * units.meter / units.second
    v = v * units.meter / units.second

    skew = SkewT(ax, rotation=45)
    skew.plot(p, t, 'r', label='Temperature')
    skew.plot(p, td, 'g', label='Dewpoint')
    skew.plot_barbs(p, u.to('knots'), v.to('knots'))
    skew.ax.set_ylim(1050, 100)
    skew.ax.set_xlim(-40, 40)
    skew.ax.grid(True, which='major', color='gray', linestyle='--', alpha=0.6)
    skew.ax.set_title(title, fontsize=9)
    skew.ax.legend(loc='upper right', fontsize=7)
    return ax

def plot_emagram_panel(ds, lat=39.72, lon=140.10, times=None, model_name="GSM"):
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
    fig.suptitle(f"{model_name} emagram\nLat: {lat:.2f}, Lon: {lon:.2f}", fontsize=13, y=1.05)
    return fig

def plot_emagram_gsm_panel(ds, lat=39.72, lon=140.10, times=None):
    return plot_emagram_panel(ds, lat=lat, lon=lon, times=times, model_name="GSM")

def plot_emagram_msm_panel(ds, lat=39.72, lon=140.10, times=None):
    return plot_emagram_panel(ds, lat=lat, lon=lon, times=times, model_name="MSM")

# ===============================================
# END OF FILE
# ===============================================
