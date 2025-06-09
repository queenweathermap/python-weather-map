# scripts/gpv_panel_local_msm_akita.py
# ========================================================
# MSM秋田局地天気図パネル（6段×12列）＋Slack自動通知
# - 秋田エリアの高解像度パネルを12時刻（3時間ごと）出力
# - 1段目: 秋田エマグラム（MSM予想値）
# - 2〜6段目: 秋田周辺の各種断面
# - データ未取得時はNO DATAパネル自動生成
# ========================================================

import sys
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- 共通DL/変換ユーティリティ ---
from scripts.gpv_downloader import download_gpv, grib2_to_nc

# --- MSMパネル描画 ---
from module.gpv_plotter_msm import (
    plot_emagram_msm,  # 1段目エマグラム
    plot_700hpa_dindex_500hpa_temp_msm,  # 2段目
    plot_850hpa_temp_wind_700hpa_w_msm,  # 3段目
    plot_850hpa_thetae_stream_msm,       # 4段目
    plot_925hpa_temp_wind_dindex_msm,    # 5段目
    plot_surface_pressure_and_wind_msm,  # 6段目
)
from module.slack_utils import send_file_to_slack

# ===============================
# 定数（ファイルパターン・保存先・範囲）
# ===============================
MSM_PATTERN = "MSM_GPV_Rjp_L-pall_FD0000-0100_grib2.bin"
BASE_DIR = "./data"
AKITA_LAT_RANGE = (38.8, 40.8)
AKITA_LON_RANGE = (139.2, 141.0)
AKITA_PIN_LAT = 39.72
AKITA_PIN_LON = 140.10

def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_nodata_weather_panel(times, save_path):
    """全データ未取得時のNO DATAパネル作成＆Slack送信"""
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
    fig.suptitle("秋田局地 MSM GPVデータ未取得（NO DATAパネル）", fontsize=16)
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[NO DATAパネル生成] {save_path}")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信エラー:", e)

def make_local_weather_panel(ds, times, save_path):
    """
    秋田局地パネル（6段×12列）の作成・保存・Slack送信
    """
    ncols = len(times)
    nrows = 6
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    init_time = pd.Timestamp(times[0])
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    for col, time in enumerate(times):
        # データ有無チェック
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

        # 1行目：秋田ピンポイントのエマグラム
        dsi_point = ds.sel(lat=AKITA_PIN_LAT, lon=AKITA_PIN_LON, time=time, method='nearest')
        ax_emagram = axes[0, col]
        ax_emagram.cla()
        plot_emagram_msm(ax_emagram, dsi_point, city_lat=AKITA_PIN_LAT, city_lon=AKITA_PIN_LON, city_name="秋田")

        # 2〜6行目：秋田周辺の水平断面
        dsi = ds.sel(
            lat=slice(AKITA_LAT_RANGE[0], AKITA_LAT_RANGE[1]),
            lon=slice(AKITA_LON_RANGE[0], AKITA_LON_RANGE[1]),
            time=time
        )
        plot_700hpa_dindex_500hpa_temp_msm(axes[1, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[2, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[3, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)

        # 1行目（エマグラム）に時刻ラベル
        ax_emagram.text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=ax_emagram.transAxes
        )

    # 2〜6段目のみグリッド線
    for row in range(1, 6):
        for col in range(ncols):
            add_gridlines(axes[row, col])

    fig.suptitle(
        f"【秋田局地版・MSM】天気図パネル（エマグラム含む）\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
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
    # 1. 最新データのダウンロード＆変換
    grib2_path, init_time = download_gpv(MSM_PATTERN, BASE_DIR)
    if grib2_path is None or not os.path.exists(grib2_path):
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3 * i) for i in range(12)]
        make_nodata_weather_panel(times, save_path="akita_panel_nodata.jpg")
        print("【ERROR】秋田局地 MSM GPVデータ未取得。NO DATAパネルを送信しました。")
        sys.exit(0)

    # 2. xarrayで開いて対象時刻リスト作成
    nc_path = grib2_to_nc(grib2_path)
    ds = xr.open_dataset(nc_path)
    times = ds.time.values[:12]
    print("==== 秋田局地 MSMパネル作成 ====")
    make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
