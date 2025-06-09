# scripts/gpv_panel_local_msm_akita.py
# ===============================
# MSM秋田局地天気図 6行×n列パネル生成 ＋ Slack自動通知
# ===============================

import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュールimport ---
from scripts.gpv_downloader import download_msm_gpv, grib2_to_nc
from module.gpv_plotter_msm import (
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_gsm,      # ※GSM/両対応ならこのままでOK
    plot_surface_pressure_and_wind_msm,
    plot_emagram_msm,
)
from module.slack_utils import send_file_to_slack

# --- 秋田局地範囲（緯度経度） ---
AKITA_LAT_RANGE = (38.8, 40.8)
AKITA_LON_RANGE = (139.2, 141.0)

def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_local_weather_panel(ds, times, save_path):
    ncols = len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )

    init_time = pd.Timestamp(times[0])
    col_labels = []
    hh_labels = []

    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    for col, time in enumerate(times):
        # 秋田局地範囲で切り出す
        dsi = ds.sel(
            lat=slice(AKITA_LAT_RANGE[0], AKITA_LAT_RANGE[1]),
            lon=slice(AKITA_LON_RANGE[0], AKITA_LON_RANGE[1]),
            time=time
        )
        plot_700hpa_dindex_500hpa_temp_msm(axes[0, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[1, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[2, col], dsi)
        plot_925hpa_temp_wind_dindex_gsm(axes[3, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[4, col], dsi)
        plot_emagram_msm(axes[5, col], dsi, city_lat=39.72, city_lon=140.10, city_name="秋田")

        axes[5, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[5, col].transAxes
        )

    for ax in axes.flatten():
        add_gridlines(ax)

    fig.suptitle(
        f"【秋田局地版・MSM】天気図パネル\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )

    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)

    # --- Slack送信 ---
    print("画像ファイルの存在:", os.path.exists(save_path))
    print(">>> Slack送信直前です")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信エラー:", e)

if __name__ == "__main__":
    # --- MSM GPV最新データのダウンロード＆変換 ---
    grib2_path, init_time = download_msm_gpv()
    nc_path = grib2_to_nc(grib2_path)
    ds = xr.open_dataset(nc_path)
    times = ds.time.values[:4]  # 必要な時刻だけ切り出し

    # --- パネル作成＆Slack送信 ---
    print("==== パネル作成 ====")
    make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
