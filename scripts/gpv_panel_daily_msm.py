# ===============================
# MSM用：1時刻の6段パネルを保存
# ===============================
import sys
import os
# この2行をスクリプトの一番最初に追加！
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LinearSegmentedColormap
from module.gpv_plotter_msm import (
    plot_300hpa_height_wind,          # 300hPa
    plot_500hpa_vorticity,          # 500hPa渦度（例）
    plot_700hpa_dindex_500hpa_temp,  # 700湿数・500温度
    plot_850hpa_temp_wind_700hpa_w,  # 850hPa温度・風
    plot_850hpa_thetae_stream,       # 850hPa相当温位
    plot_surface_pressure_and_wind,  # 地上
)

def make_daily_weather_panel_multi_time(ds, times, save_path):
    fig, axes = plt.subplots(nrows=5, ncols=len(times), figsize=(4*len(times), 10),
                             subplot_kw={"projection": ccrs.PlateCarree()})
    for col, time in enumerate(times):
        dsi = ds.sel(time=time)
        plot_300hpa_height_wind(axes[0, col], dsi)
        plot_700hpa_temp_rh(axes[1, col], dsi)
        plot_850hpa_temp_wind_w(axes[2, col], dsi)
        plot_850hpa_thetae_stream(axes[3, col], dsi)
        plot_surface_pressure_and_wind(axes[4, col], dsi)
    plt.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close()
