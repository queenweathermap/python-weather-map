# scripts/gpv_panel_daily_gsm.py
# ===============================
# GSM天気図 5行×n列パネル生成 ＋ Slack自動通知
#  - GPV自動DL/変換も統合
#  - GitHub Actions/ローカル両対応
# ===============================

import sys
import os
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュールimport（GPV自動DL&変換ユーティリティ） ---
from scripts.gpv_downloader import download_gsm_gpv, grib2_to_nc

# --- 描画関数・Slack通知ユーティリティ ---
from module.gpv_plotter_gsm import (
    plot_300hpa_height_wind_gsm,
    plot_500hpa_vorticity_gsm,
    plot_700hpa_dindex_500hpa_temp_gsm,
    plot_850hpa_temp_wind_700hpa_w_gsm,
    plot_850hpa_thetae_stream_gsm,
    plot_surface_pressure_and_wind_gsm,
)

# --- Slack送信用ユーティリティ
from module.slack_utils import send_file_to_slack

# ===============================
# 緯度経度グリッド線を全パネルに追加
# ===============================
def add_gridlines(ax):
    """
    サブプロットaxに緯度経度グリッド線を追加
    """
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl


# ===============================
# GSM用：6行×n列パネル作成メイン関数
# ===============================
def make_daily_weather_panel_multi_time(ds, times, save_path):
    """
    1日n時刻×6要素のパネルを描画し、1枚画像で保存＆Slack送信
    """
    ncols = len(times)
    figsize = (4 * ncols, 21)  # ← 6段用に高さも拡大

    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    if axes.ndim == 1:
        axes = axes.reshape((6, 1))
    elif axes.shape[0] != 6:
        axes = axes.reshape((6, -1))

    # --- 初期時刻＆ラベル準備 ---
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels = []
    hh_labels = []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # --- 各パネル描画 ---
    for col, time in enumerate(times):
        dsi = ds.sel(time=time)
        plot_300hpa_height_wind_gsm(axes[0, col], dsi)
        plot_500hpa_vorticity_gsm(axes[1, col], dsi)
        plot_700hpa_dindex_500hpa_temp_gsm(axes[2, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_gsm(axes[3, col], dsi)
        plot_850hpa_thetae_stream_gsm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_gsm(axes[5, col], dsi)  # ← 6段目を追加

        # 6段目の下に「時刻+経過時間」ラベル
        axes[5, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[5, col].transAxes
        )

    # --- 全パネル一括で緯度・経度線追加 ---
    for ax in axes.flatten():
        add_gridlines(ax)

    # --- パネル全体タイトル ---
    fig.suptitle(
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )

    # --- 画像保存 ---
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)

    # --- Slackへ送信 ---
    print("画像ファイルの存在:", os.path.exists(save_path))
    print(">>> Slack送信直前です")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信で例外:", e)
    print(">>> Slack送信後です")

    # --- メイン処理 ---
    if __name__ == "__main__":
        # --- 1. 最新データのダウンロード＆変換 ---
        grib2_path, init_time = download_gsm_gpv()
        nc_path = grib2_to_nc(grib2_path)
    
        # --- 2. xarrayで開いて対象時刻リスト作成 ---
        ds = xr.open_dataset(nc_path)
        times = ds.time.values[:4]  # ← 必要に応じて全時刻/間引き等
    
        # --- 3. パネル作成＆Slack送信 ---
        print("==== パネル作成 ====")
        make_daily_weather_panel_multi_time(ds, times, "weather_map.jpg")
        print("==== 完了 ====")
