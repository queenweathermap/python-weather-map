# scripts/gpv_panel_daily_gsm.py
# ===============================
# GSM天気図 6行×n列パネル生成 ＋ Slack自動通知
#  - GPV自動DL/変換も統合
#  - GitHub Actions/ローカル両対応
#  - データ未取得時はNO DATAパネル自動生成
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
from module.gpv_plotter_gsm import (
    plot_300hpa_height_wind_gsm,
    plot_500hpa_vorticity_gsm,
    plot_700hpa_dindex_500hpa_temp_gsm,
    plot_850hpa_temp_wind_700hpa_w_gsm,
    plot_850hpa_thetae_stream_gsm,
    plot_925hpa_temp_wind_dindex_gsm,
    plot_surface_pressure_and_wind_gsm,
    plot_emagram_gsm,
)
from module.slack_utils import send_file_to_slack

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
    fig.suptitle("GPVデータ未取得（NO DATAパネル）", fontsize=16)
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
        plot_300hpa_height_wind_gsm(axes[0, col], dsi)
        plot_500hpa_vorticity_gsm(axes[1, col], dsi)
        plot_700hpa_dindex_500hpa_temp_gsm(axes[2, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_gsm(axes[3, col], dsi)
        plot_850hpa_thetae_stream_gsm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_gsm(axes[5, col], dsi)
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
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
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
# 設定（パターン名と保存先ディレクトリ）
# ===============================
GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",
]
BASE_DIR = "./data"

if __name__ == "__main__":
    # 1. 最新データのダウンロード＆変換
    downloaded = download_gpv_all(GSM_PATTERNS, base_dir=BASE_DIR)
    if not downloaded or len(downloaded) < 2:
        # データ取得失敗時はNO DATAパネル送信
        # 適当な時刻ラベルを生成
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
        make_nodata_weather_panel(times, "gsm_panel_nodata.jpg")
        print("【ERROR】GPVファイル未取得。NO DATAパネル送信処理へ…")
        sys.exit(1)

    # 2. NetCDF変換とmerge
    nc_paths = [grib2_to_nc(path) for path, _ in downloaded]
    nc_l_pall = [p for p in nc_paths if "L-pall" in p][0]
    nc_lsurf  = [p for p in nc_paths if "Lsurf"  in p][0]
    ds_l_pall = xr.open_dataset(nc_l_pall)
    ds_lsurf  = xr.open_dataset(nc_lsurf)
    ds = xr.merge([ds_l_pall, ds_lsurf])

    # --- 3. パネル作成＆Slack送信 ---
    times = ds.time.values[:12]  # 3時間刻み12本
    print("==== パネル作成 ====")
    make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
