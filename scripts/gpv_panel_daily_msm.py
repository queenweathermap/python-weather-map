# scripts/gpv_panel_daily_msm.py
# ===============================
# MSM天気図 6行×n列パネル生成 ＋ Slack自動通知
# ===============================

import sys
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュールimport ---
from scripts.gpv_downloader import download_gpv_all, grib2_to_nc
from module.gpv_plotter_msm import (
    plot_500hpa_vorticity_msm,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)
from module.slack_utils import send_file_to_slack

# ===============================
# MSMパターンリストと保存先
# ===============================
MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
    # 必要なら地上や他層も追加
]
BASE_DIR = "./data"

def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_nodata_weather_panel(times, save_path):
    nrows, ncols = 6, len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize)
    for col in range(ncols):
        for row in range(nrows):
            ax = axes[row, col]
            ax.set_facecolor("white")
            for spine in ax.spines.values():
                spine.set_edgecolor("gray")
                spine.set_linewidth(1)
            ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
            ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
    fig.suptitle("MSM GPVデータ未取得（NO DATAパネル）", fontsize=16)
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[NO DATAパネル生成] {save_path}")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信エラー:", e)

def make_daily_weather_panel_multi_time(ds, times, save_path):
    ncols = len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    if axes.ndim == 1:
        axes = axes.reshape((6, 1))
    elif axes.shape[0] != 6:
        axes = axes.reshape((6, -1))

    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    for col, time in enumerate(times):
        if np.datetime64(time) not in ds.time.values:
            for row in range(6):
                ax = axes[row, col]
                ax.set_facecolor("white")
                for spine in ax.spines.values():
                    spine.set_edgecolor("gray")
                    spine.set_linewidth(1)
                ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
            continue
        dsi = ds.sel(time=time)
        plot_500hpa_vorticity_msm(axes[0, col], dsi)
        plot_700hpa_dindex_500hpa_temp_msm(axes[1, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[2, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[3, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)
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
        f"MSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))
    print(">>> Slack送信直前です")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信エラー:", e)

# ===============================
# メイン処理
# ===============================
if __name__ == "__main__":
    # 1. 最新データのダウンロード＆分割NetCDF変換
    downloaded = download_gpv_all(MSM_PATTERNS, base_dir=BASE_DIR)
    if not downloaded or len(downloaded) < 3:
        # どれか一つでも無い場合はNO DATA
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
        make_nodata_weather_panel(times, "msm_panel_nodata.jpg")
        print("【ERROR】MSM GPVデータ未取得。NO DATAパネルを送信しました。")
        sys.exit(1)

    # 2. NetCDF変換し結合
    nc_paths = [grib2_to_nc(path) for path, _ in downloaded]
    # NetCDFを全部読み込んで「時刻結合」
    ds_list = [xr.open_dataset(nc) for nc in nc_paths]
    ds = xr.concat(ds_list, dim="time")

    # --- 3. パネル作成＆Slack送信 ---
    times = ds.time.values[:12]  # MSMも12時刻
    print("==== MSMパネル作成 ====")
    make_daily_weather_panel_multi_time(ds, times, "msm_weather_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
