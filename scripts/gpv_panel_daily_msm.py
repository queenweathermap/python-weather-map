# ===============================
# MSM用：1時刻の6段パネルを保存
# ===============================
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAexGothic'
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from module.gpv_plotter_msm import (
    plot_300hpa_height_wind_msm,         # 300hPa
    plot_500hpa_vorticity_msm,           # 500hPa渦度
    plot_700hpa_dindex_500hpa_temp_msm,  # 700hPa湿数・500hPa温度
    plot_850hpa_temp_wind_700hpa_w_msm,  # 850hPa温度・風・700hPa鉛直流
    plot_850hpa_thetae_stream_msm,       # 850hPa相当温位
    plot_surface_pressure_and_wind_msm,  # 地上
)

def make_daily_weather_panel_multi_time(ds, times, save_path):
    fig, axes = plt.subplots(nrows=6, ncols=len(times), figsize=(4*len(times), 12),
                             subplot_kw={"projection": ccrs.PlateCarree()})
    for col, time in enumerate(times):
        dsi = ds.sel(time=time)
        plot_300hpa_height_wind_msm(axes[0, col], dsi)
        plot_500hpa_vorticity_msm(axes[1, col], dsi)
        plot_700hpa_dindex_500hpa_temp_msm(axes[2, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[3, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)
    plt.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close()
