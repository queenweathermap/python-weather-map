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

# --- サブモジュールimport（GPV自動DL&変換ユーティリティ） ---
from scripts.gpv_downloader import download_gsm_gpv, grib2_to_nc

# --- 描画関数・Slack通知ユーティリティ ---
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

# ===============================
# グリッド線追加
# ===============================
def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

# ===============================
# NO DATAパネル生成関数
# ===============================
def make_nodata_weather_panel(times, save_path):
    """
    すべての時刻でデータが無い場合に「NO DATA」だけを並べたパネルを作る
    """
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

# ===============================
# GSM用：6行×n列パネル作成メイン関数
# ===============================
def make_daily_weather_panel_multi_time(ds, times, save_path):
    """
    1日n時刻×6要素のパネルを描画し、1枚画像で保存＆Slack送信
    """
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
        # データ有無を判定
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

    # --- 全パネル一括で緯度・経度線追加 ---
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
# メイン処理
# ===============================
if __name__ == "__main__":
    # --- 1. 最新データのダウンロード＆変換 ---
    grib2_path, init_time = download_gsm_gpv()
    if grib2_path is None or not os.path.exists(grib2_path):
        # 「NO DATA」パネルだけを出す
        # timesは想定する時刻リストで生成
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3 * i) for i in range(12)]
        make_nodata_weather_panel(times, save_path="gsm_panel_nodata.jpg")
        print("【ERROR】GPVデータ未取得。NO DATAパネルを送信しました。")
        sys.exit(0)

    # --- 2. xarrayで開いて対象時刻リスト作成 ---
    nc_path = grib2_to_nc(grib2_path)
    ds = xr.open_dataset(nc_path)
    times = ds.time.values[:12]  # 3時間刻み12本など

    # --- 3. パネル作成＆Slack送信 ---
    print("==== パネル作成 ====")
    make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
